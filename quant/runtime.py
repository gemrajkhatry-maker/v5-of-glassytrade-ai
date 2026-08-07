"""QuantEngine — the deterministic single-threaded event loop.

Consumes ticks from a ``BrokerGateway``, aggregates them into bars, drives the
pipeline AuctionCoordinator -> DecisionService -> PaperOMS -> ExitEngine ->
SessionRisk, and emits typed events. Purely deterministic: replaying the same
tick sequence always yields the same event trace.

Only imports ``quant.*`` and stdlib — zero backend/ imports.
"""

from __future__ import annotations

from dataclasses import asdict

from quant.aggregator import BarAggregator
from quant.coordinator import AuctionCoordinator
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import clamp_quantity
from quant.events import (
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    Event,
    EventBus,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
    SignalApproved,
)
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.persistence import Journal
from quant.state import StateProjector


class QuantEngine:
    def __init__(
        self,
        gateway,
        symbol: str,
        interval_seconds: int = 60,
        journal_path: str | None = None,
        min_rr: float = 1.5,
        tick_size: float = 0.05,
        time_stop_bars: int = 60,
    ) -> None:
        self._gateway = gateway
        self.symbol = symbol
        self._tick_size = tick_size
        self._aggregator = BarAggregator(interval_seconds=interval_seconds)
        self._coordinator = AuctionCoordinator()
        self._decision_service = DecisionService(min_rr=min_rr)
        self._oms = PaperOMS()
        self._exits = ExitEngine(time_stop_bars=time_stop_bars)
        self._risk = SessionRisk()
        self._bus = EventBus()
        self._projector = StateProjector()
        self._journal = Journal(path=journal_path) if journal_path else None
        self._trace: list[Event] = []
        self._position = None
        self._bar_index = 0
        self._entry_bar_index = 0
        self._subscribed = False

    def run(self, max_steps: int | None = None) -> list[Event]:
        """Consume ticks from the gateway, drive the full pipeline, and return
        the event trace. Deterministic: same ticks -> same trace."""
        if not self._subscribed:
            self._gateway.subscribe(self.symbol)
            self._subscribed = True
        steps = 0
        while True:
            if max_steps is not None and steps >= max_steps:
                break
            tick = self._gateway.next_tick()
            if tick is None:
                break
            steps += 1
            bar = self._aggregator.add_tick(tick)
            if bar is not None:
                self._on_bar_closed(bar)
        return list(self._trace)

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._trace)

    @property
    def projector(self) -> StateProjector:
        return self._projector

    def _on_bar_closed(self, bar) -> None:
        state = self._coordinator.on_bar_close(bar)
        self._bar_index += 1
        self._emit(BarClosed(symbol=self.symbol, time=bar.time, bar=bar))
        self._emit(AuctionUpdated(symbol=self.symbol, time=bar.time, auction=state))

        if self._position is None:
            self._decide(state, bar)
        else:
            self._manage_exit(state, bar)

    def _decide(self, state, bar) -> None:
        ctx = DecisionContext(
            state=state,
            bar=bar,
            symbol=self.symbol,
            session_open=True,
            warmup_complete=True,
            position_open=False,
            cooldown_remaining_sec=0,
            risk_halted=False,
            agent_direction="LONG",
            agent_probability=0.7,
            tick_size=self._tick_size,
        )
        decision = self._decision_service.evaluate(ctx)
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=decision))

        if decision.approved and decision.signal is not None:
            signal = decision.signal
            self._emit(SignalApproved(symbol=self.symbol, time=bar.time, signal=signal))
            quantity = clamp_quantity(self._risk.position_size(signal.entry, signal.sl))
            position = self._oms.submit(signal, quantity)
            self._entry_bar_index = self._bar_index
            self._position = position
            self._emit(PositionOpened(symbol=self.symbol, time=bar.time, position=position))

    def _manage_exit(self, state, bar) -> None:
        held_bars = self._bar_index - self._entry_bar_index
        exit_dec = self._exits.evaluate(self._position, state, bar_index=held_bars)
        if exit_dec.should_exit:
            fill = self._oms.close(self._position, exit_dec.close_price, bar.time,
                                   exit_dec.reason)
            self._position = None
            self._emit(PositionClosed(symbol=self.symbol, time=bar.time, fill=fill))
            risk = self._risk.record_trade(fill.pnl)
            self._emit(RiskUpdated(symbol=self.symbol, time=bar.time, risk=risk))

    def _emit(self, event: Event) -> None:
        """Publish to the bus, append to the trace, fold into the projector,
        and persist a JSON-serializable record to the journal."""
        self._bus.publish(event)
        self._trace.append(event)
        self._projector.on_event(event)
        if self._journal is not None:
            self._journal.append({"type": event.__class__.__name__, **asdict(event)})
