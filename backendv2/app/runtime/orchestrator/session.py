"""Session runtime for deterministic stage execution."""

from __future__ import annotations

import logging


from app.runtime.feeds import FeedSource
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.candle_builder import CandlePipeline
from app.runtime.pipeline.execution import ExecutionPipeline
from app.runtime.pipeline.broker_sync import BrokerSynchronization
from app.runtime.pipeline.features import FeatureComputation
from app.runtime.pipeline.gates import GateEvaluation
from app.runtime.pipeline.market_structure import MarketStructureAnalysis
from app.runtime.pipeline.microstructure import MicrostructureAnalysis
from app.runtime.pipeline.normalizer import TickNormalizer
from app.runtime.pipeline.orderflow import OrderFlowPipeline
from app.runtime.pipeline.persistence import EventPersistence
from app.runtime.pipeline.position import PositionLifecycle
from app.runtime.pipeline.risk import RiskEvaluation
from app.runtime.pipeline.sequencer import TickSequencer
from app.runtime.pipeline.signal import SignalGeneration
from app.runtime.pipeline.telemetry import TelemetryPipeline
from app.runtime.pipeline.strategy import StrategyEvent, StrategyRuntime
from app.runtime.pipeline.events import CandleTimeframe, OrderStatusEvent, PositionEvent, Signal, Tick

logger = logging.getLogger(__name__)


class SessionRuntime:
    """Deterministic session-scoped pipeline runner."""

    def __init__(self, feed: FeedSource, symbols: list[str]):
        self._feed = feed
        self._symbols = symbols
        self._sequencer = TickSequencer()
        self._normalizer = TickNormalizer(symbols=self._symbols, strict_symbol_mode=True)
        self._candles = CandlePipeline()
        self._market_structure = MarketStructureAnalysis()
        self._orderflow = OrderFlowPipeline()
        self._microstructure = MicrostructureAnalysis()
        self._features = FeatureComputation()
        self._signal = SignalGeneration()
        self._gates = GateEvaluation()
        self._risk = RiskEvaluation()
        self._position = PositionLifecycle()
        self._execution = ExecutionPipeline()
        self._broker_sync = BrokerSynchronization()
        self._persistence = EventPersistence()
        self._telemetry = TelemetryPipeline()
        self._strategy = StrategyRuntime()
        self._running = False
        self._metrics = StageMetrics(stage_name="SessionRuntime")
        self._event_count = 0

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._feed.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self._feed.stop()
        finally:
            self._persistence.flush()

    def run_once(self, max_ticks: int | None = None) -> list[object]:
        if not self._running:
            raise RuntimeError("SessionRuntime not started")
        events = []
        i = 0
        feed_iter = iter(self._feed.stream())
        while max_ticks is None or i < max_ticks:
            try:
                tick = next(feed_iter)
            except StopIteration:
                break
            if max_ticks is not None and i >= max_ticks:
                break
            i += 1
            events.extend(self._process_tick(tick))
            if max_ticks is not None and len(events) > max_ticks * 20:
                # guardrail: keep deterministic cap in hot path
                break
        return events

    def _process_tick(self, tick: Tick) -> list[object]:
        stage_events = []
        self._event_count += 1
        span_id = self._event_count
        self._telemetry.start_span(span_id)
        try:
            seq = self._sequencer.process(tick)
            if seq is None:
                return []

            normalized = self._normalizer.process(seq)
            if normalized is None:
                return []
            stage_events.append(normalized)

            candle_events = self._candles.process(normalized)
            orderflow_events = self._orderflow.process(normalized)
            micro_events = self._microstructure.process(normalized)
            market_events: list[object] = []
            if candle_events:
                for candle in candle_events:
                    if candle.timeframe == CandleTimeframe.M1:
                        market_events = self._market_structure.process(candle)
                        break

            for metric in orderflow_events:
                self._features.ingest_orderflow(metric)
                self._signal.ingest_orderflow(metric)
            for metric in micro_events:
                self._features.ingest_microstructure(metric)
                self._signal.ingest_microstructure(metric)
            for metric in market_events:
                self._features.ingest_market_structure(metric)
                self._signal.ingest_market_structure(metric)

            stage_events.extend(orderflow_events)
            stage_events.extend(micro_events)
            stage_events.extend(market_events)

            for candle in candle_events:
                self._features.ingest_market_structure(self._market_structure.get_result(candle.symbol))
                self._signal.ingest_market_structure(self._market_structure.get_result(candle.symbol))

                # strategy stage kept explicit for future branching
                features = self._features.process(candle)
                for feature in features:
                    for item in self._strategy.process(feature):
                        if isinstance(item, StrategyEvent):
                            stage_events.append(item)
                            payload = item.payload
                        else:
                            payload = item
                        if isinstance(payload, Signal):
                            stage_events.append(payload)
                            self._run_signal_flow(payload, stage_events)
                    for signal in self._signal.process(feature):
                        self._run_signal_flow(signal, stage_events)

            for evt in stage_events:
                self._telemetry.process(evt)
            persisted = self._persistence.process(normalized)
            if persisted:
                stage_events.extend(persisted)
        except Exception:
            logger.exception("Session runtime failed while processing tick")
            self._metrics.record_error()
        finally:
            self._telemetry.end_span("SessionRuntime", span_id)
        return [e for e in stage_events if e is not None]

    def _run_signal_flow(self, signal: Signal, stage_events: list[object]) -> None:
        gates = self._gates.process(signal)
        stage_events.extend(gates)
        for gate in gates:
            risks = self._risk.process(gate)
            stage_events.extend(risks)
            for risk in risks:
                if not risk.approved:
                    continue
                position_events = self._position.process(signal)
                stage_events.extend(position_events)
                for position_event in position_events:
                    self._risk.sync_position_event(position_event)
                    self._run_order_events(position_event, stage_events)

    def _run_order_events(self, position_event: object, stage_events: list[object]) -> None:
        order_events = self._execution.process(position_event)
        if not isinstance(order_events, list):
            order_events = []
        terminal_status = None
        if not order_events:
            terminal_status = self._handle_execution_gap(position_event)
            if terminal_status is not None:
                order_events = [terminal_status]

        for order_event in order_events:
            if order_event is None:
                continue
            stage_events.append(order_event)
            if order_event.status in {"REJECTED", "CANCELLED"}:
                self._position.process(order_event)
                self._risk.retract_position(order_event.symbol, order_event.order_id)
                continue

            if order_event.status in {"FILLED", "PARTIAL", "PENDING"}:
                fills = self._broker_sync.process(order_event)
                stage_events.extend(fills)
                for fill in fills:
                    if fill.order_id != order_event.order_id:
                        continue
                    close_events = self._position.process(fill)
                    for close_event in close_events:
                        self._risk.sync_position_event(close_event)
                    stage_events.extend(close_events)

                persisted = self._persistence.process(order_event)
                if persisted:
                    stage_events.extend(persisted)

    @staticmethod
    def _handle_execution_gap(position_event: object) -> OrderStatusEvent | None:
        if not isinstance(position_event, PositionEvent):
            return None
        symbol = getattr(position_event, "symbol", "")
        order_id = getattr(position_event, "position_id", "")
        return OrderStatusEvent(
            order_id=order_id,
            symbol=symbol,
            status="REJECTED",
            timestamp=getattr(position_event, "timestamp", 0.0),
            reject_reason="No execution status returned",
        )

    def register_strategy(
        self,
        symbol: str,
        strategy_id: str,
        handler,
        *,
        priority: int = 100,
        replace: bool = False,
    ) -> None:
        self._strategy.register(
            symbol=symbol,
            strategy_id=strategy_id,
            handler=handler,
            priority=priority,
            replace=replace,
        )

    def unregister_strategy(self, symbol: str, strategy_id: str) -> None:
        self._strategy.unregister(symbol=symbol, strategy_id=strategy_id)

    def bind_broker(self, broker) -> None:
        self._execution._broker = broker

    def strategy_bindings(self) -> dict[str, dict]:
        return self._strategy.snapshot()

    def warmup(self) -> None:
        self._sequencer.warmup()
        self._normalizer.warmup()
        self._candles.warmup()
        self._market_structure.warmup()
        self._orderflow.warmup()
        self._microstructure.warmup()
        self._features.warmup()
        self._signal.warmup()
        self._gates.warmup()
        self._risk.warmup()
        self._position.warmup()
        self._execution.warmup()
        self._broker_sync.warmup()
        self._persistence.warmup()
        self._telemetry.warmup()
        self._strategy.warmup()

    def teardown(self) -> None:
        self.stop()
        self._sequencer.teardown()
        self._normalizer.teardown()
        self._candles.teardown()
        self._market_structure.teardown()
        self._orderflow.teardown()
        self._microstructure.teardown()
        self._features.teardown()
        self._signal.teardown()
        self._gates.teardown()
        self._risk.teardown()
        self._position.teardown()
        self._execution.teardown()
        self._broker_sync.teardown()
        self._persistence.teardown()
        self._telemetry.teardown()
        self._strategy.teardown()
