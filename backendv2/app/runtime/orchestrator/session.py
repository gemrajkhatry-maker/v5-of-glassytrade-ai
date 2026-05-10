"""Session runtime for deterministic stage execution."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import os
import time

from app.runtime.contracts import (
    ReadinessCheck,
    RuntimeHealth,
    RuntimeReadiness,
    RuntimeSessionState,
)
from app.runtime.feeds import FeedSource
from app.runtime.pipeline import StageMetrics
from app.domain.shared.port.storage import IStorage
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
from dataclasses import asdict

logger = logging.getLogger(__name__)


class SessionRuntime:
    """Deterministic session-scoped pipeline runner."""

    def __init__(self, feed: FeedSource, symbols: list[str], storage: IStorage | None = None):
        self._feed = feed
        self._symbols = symbols
        self._storage = storage  # Store storage reference for injection
        self._state_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._sequencer = TickSequencer()
        self._normalizer = TickNormalizer(symbols=self._symbols, strict_symbol_mode=True)
        self._candles = CandlePipeline()
        self._orderflow = OrderFlowPipeline()
        self._microstructure = MicrostructureAnalysis()
        self._features = FeatureComputation()
        self._signal = SignalGeneration()
        self._risk = RiskEvaluation()
        self._position = PositionLifecycle()
        self._execution = ExecutionPipeline()
        self._broker_sync = BrokerSynchronization()
        self._persistence = EventPersistence(storage=storage)
        self._market_structure = MarketStructureAnalysis(storage=storage)  # Inject storage directly
        self._telemetry = TelemetryPipeline()
        self._strategy = StrategyRuntime()
        self._gates = GateEvaluation(
            equity_fn=lambda symbol: float(self._position.get_portfolio(symbol).equity)
        )
        self._running = False
        self._metrics = StageMetrics(stage_name="SessionRuntime")
        self._event_count = 0
        self._history: dict[str, list[dict[str, object]]] = {symbol: [] for symbol in symbols}
        self._run_in_progress = False
        self._session_state = RuntimeSessionState.NEW
        self._startup_window_started_at: float | None = None

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    @property
    def event_count(self) -> int:
        return self._event_count

    def ready_readiness(self) -> RuntimeReadiness:
        feed_snapshot = self._feed.snapshot() if hasattr(self._feed, "snapshot") else {}
        execution_snapshot = self._execution.snapshot()
        broker_bound = bool(execution_snapshot.get("broker_bound", False))
        feed_running = bool(feed_snapshot.get("running", False))
        ticks_seen = int(feed_snapshot.get("ticks_seen", 0) or 0)
        state = str(feed_snapshot.get("state", "")).lower()
        producer_error = str(feed_snapshot.get("producer_error", "") or "")
        first_tick_age_sec = feed_snapshot.get("first_tick_age_sec")
        last_tick_age_sec = feed_snapshot.get("last_tick_age_sec")
        startup_window_sec = float(os.getenv("RUNTIME_STARTUP_TICK_WINDOW_SEC", "30"))
        startup_window_elapsed = (
            time.monotonic() - (self._startup_window_started_at or time.monotonic())
        ) if self._startup_window_started_at is not None else None

        checks: list[ReadinessCheck] = []
        if self._session_state != RuntimeSessionState.RUNNING:
            checks.append(
                ReadinessCheck(
                    name="session_state",
                    status=RuntimeHealth.NOT_READY,
                    reason=f"session_state={self._session_state.value}",
                )
            )
        else:
            checks.append(
                ReadinessCheck(
                    name="session_state",
                    status=RuntimeHealth.HEALTHY,
                    reason="session running",
                )
            )

        if not broker_bound:
            checks.append(
                ReadinessCheck(
                    name="broker",
                    status=RuntimeHealth.UNSAFE_TO_TRADE,
                    reason="broker_not_bound",
                )
            )
        else:
            checks.append(ReadinessCheck(name="broker", status=RuntimeHealth.HEALTHY, reason="broker_bound"))

        if state == "drained":
            checks.append(
                ReadinessCheck(
                    name="feed_state",
                    status=RuntimeHealth.UNSAFE_TO_TRADE,
                    reason="feed_drained",
                )
            )
        elif state == "failed":
            checks.append(
                ReadinessCheck(
                    name="feed_state",
                    status=RuntimeHealth.UNSAFE_TO_TRADE,
                    reason="feed_failed",
                )
            )
        elif not feed_running:
            checks.append(
                ReadinessCheck(
                    name="feed_running",
                    status=RuntimeHealth.NOT_READY,
                    reason="feed_not_running",
                )
            )
        else:
            checks.append(
                ReadinessCheck(name="feed_running", status=RuntimeHealth.HEALTHY, reason="feed_running")
            )

        if producer_error:
            checks.append(
                ReadinessCheck(
                    name="feed_error",
                    status=RuntimeHealth.UNSAFE_TO_TRADE,
                    reason=producer_error,
                )
            )

        if ticks_seen <= 0:
            if startup_window_elapsed is not None and startup_window_elapsed > startup_window_sec:
                checks.append(
                    ReadinessCheck(
                        name="startup_window",
                        status=RuntimeHealth.UNSAFE_TO_TRADE,
                        reason="no_ticks_within_startup_window",
                    )
                )
            checks.append(
                ReadinessCheck(
                    name="ticks_seen",
                    status=RuntimeHealth.UNSAFE_TO_TRADE,
                    reason="no_ticks_seen",
                )
            )

        if isinstance(last_tick_age_sec, (int, float)) and last_tick_age_sec > 30:
            checks.append(
                ReadinessCheck(
                    name="feed_stale",
                    status=RuntimeHealth.DEGRADED,
                    reason="last_tick_age_sec > 30",
                )
            )

        status = RuntimeHealth.HEALTHY
        for check in checks:
            if check.status == RuntimeHealth.UNSAFE_TO_TRADE:
                status = RuntimeHealth.UNSAFE_TO_TRADE
                break
            if check.status == RuntimeHealth.DEGRADED and status == RuntimeHealth.HEALTHY:
                status = RuntimeHealth.DEGRADED

        return RuntimeReadiness(
            status=status,
            checks=tuple(checks),
            feed_present=len(self._symbols) > 0,
            feed_running=feed_running,
            broker_bound=broker_bound,
            ticks_seen=ticks_seen,
            first_tick_age_sec=(
                float(first_tick_age_sec)
                if isinstance(first_tick_age_sec, (int, float))
                else None
            ),
            last_tick_age_sec=(
                float(last_tick_age_sec)
                if isinstance(last_tick_age_sec, (int, float))
                else None
            ),
            last_feed_error=producer_error,
            startup_ready=(
                self._session_state == RuntimeSessionState.RUNNING
                and broker_bound
                and feed_running
                and ticks_seen > 0
                and not producer_error
            ),
        )

    @property
    def session_state(self) -> RuntimeSessionState:
        return self._session_state

    def get_history(self, symbol: str, max_points: int = 500) -> list[dict[str, object]]:
        if not symbol:
            return []
        return list(self._history.get(symbol, []))[:max_points]

    def snapshot(self, symbol: str | None = None) -> dict:
        snapshot = {
            "session_state": self._session_state.value,
            "run_in_progress": self._run_in_progress,
            "_event_count": self._event_count,
            "_event_count_by_symbol": {sym: len(self._history.get(sym, [])) for sym in self._symbols},
            "feed": self._feed.snapshot(),
            "sequencer": self._sequencer.snapshot(),
            "normalizer": self._normalizer.snapshot(),
            "candles": self._candles.snapshot(),
            "orderflow": self._orderflow.snapshot(),
            "microstructure": self._microstructure.snapshot(),
            "features": self._features.snapshot(),
            "market_structure": self._market_structure.snapshot(),
            "signal": self._signal.snapshot(),
            "gates": self._gates.snapshot(),
            "risk": self._risk.snapshot(),
            "portfolio": self._position.snapshot(),
            "execution": self._execution.snapshot(),
            "broker_sync": self._broker_sync.snapshot(),
            "persistence": self._persistence.snapshot(),
            "telemetry": self._telemetry.snapshot(),
            "strategy": self._strategy.snapshot(),
        }
        snapshot["state_digest"] = self.state_digest_payload(snapshot)

        if symbol:
            if symbol in self._position.snapshot():
                snapshot["portfolio"] = {symbol: self._position.snapshot()[symbol]}
            if symbol in self._risk.snapshot():
                snapshot["risk"] = {symbol: self._risk.snapshot()[symbol]}
            if symbol in self._gates.snapshot():
                snapshot["gates"] = {symbol: self._gates.snapshot()[symbol]}
            if symbol in self._orderflow.snapshot():
                snapshot["orderflow"] = {symbol: self._orderflow.snapshot()[symbol]}
            if symbol in self._microstructure.snapshot():
                snapshot["microstructure"] = {symbol: self._microstructure.snapshot()[symbol]}
            if symbol in self._normalizer.snapshot()["profiles"]:
                snapshot["normalizer"] = {
                    "profiles": {symbol: self._normalizer.snapshot()["profiles"].get(symbol, {})},
                    "allowed_symbols": [symbol] if symbol in self._symbols else [],
                    "strict_symbol_mode": self._normalizer.snapshot().get("strict_symbol_mode", False),
                }
            snapshot["_symbol"] = symbol

        return snapshot

    @staticmethod
    def state_digest_payload(payload: dict) -> str:
        digest_payload = dict(payload)
        digest_payload.pop("state_digest", None)
        encoded = json.dumps(digest_payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def state_digest(self, symbol: str | None = None) -> str:
        """Stable digest used to compare runtime sessions."""
        payload = self.snapshot(symbol=symbol)
        return str(payload.get("state_digest", self.state_digest_payload(payload)))

    def start(self) -> None:
        with self._state_lock:
            if self._session_state == RuntimeSessionState.RUNNING:
                return
            if self._session_state in {
                RuntimeSessionState.STOPPING,
                RuntimeSessionState.FAILED,
            }:
                raise RuntimeError(f"invalid_start_state: {self._session_state.value}")
            self._session_state = RuntimeSessionState.STARTING
            self._startup_window_started_at = time.monotonic()
            try:
                self._feed.start()
                self._running = True
                self._session_state = RuntimeSessionState.RUNNING
            except Exception:
                self._session_state = RuntimeSessionState.FAILED
                self._startup_window_started_at = None
                raise

    def stop(self) -> None:
        with self._state_lock:
            if self._session_state in {RuntimeSessionState.STOPPING, RuntimeSessionState.STOPPED}:
                return
            if self._session_state == RuntimeSessionState.NEW:
                self._session_state = RuntimeSessionState.STOPPED
                return
            self._session_state = RuntimeSessionState.STOPPING
            self._running = False
            self._startup_window_started_at = None
        try:
            self._feed.stop()
        finally:
            self._persistence.flush()
            with self._state_lock:
                self._session_state = RuntimeSessionState.STOPPED

    def run_once(self, max_ticks: int | None = None) -> list[object]:
        if self._session_state != RuntimeSessionState.RUNNING:
            raise RuntimeError(f"session_not_running: {self._session_state.value}")

        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("run_in_progress")

        self._run_in_progress = True
        events = []
        i = 0
        feed_iter = iter(self._feed.stream())
        try:
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
        except Exception:
            self._session_state = RuntimeSessionState.FAILED
            raise
        finally:
            self._run_in_progress = False
            self._run_lock.release()
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
            self._risk.observe_price(
                normalized.symbol,
                normalized.price,
                normalized.timestamp,
            )

            candle_events = self._candles.process(normalized)
            for candle in candle_events:
                payload = asdict(candle)
                payload["symbol"] = candle.symbol
                payload["timeframe"] = candle.timeframe.value if hasattr(candle.timeframe, "value") else str(candle.timeframe)
                self._history.setdefault(candle.symbol, []).append(payload)
                if len(self._history[candle.symbol]) > 500:
                    self._history[candle.symbol] = self._history[candle.symbol][-500:]
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
                self._gates.ingest_orderflow(getattr(metric, 'symbol', 'UNKNOWN'), metric)
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
                self._gates.ingest_candle(candle.symbol, candle)
                self._gates.ingest_market_structure(candle.symbol, self._market_structure.get_result(candle.symbol))

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
        if self._session_state == RuntimeSessionState.STOPPING:
            raise RuntimeError("cannot_bind_while_stopping")
        if self._session_state == RuntimeSessionState.FAILED:
            raise RuntimeError("cannot_bind_while_failed")
        self._execution.bind(broker)

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
