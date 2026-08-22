"""Orderflow signal aggregator — per-instrument trade-lifecycle state machine.

Consumes the domain ``Signal`` stream from the detectors and advances each
instrument through WATCHING → POSITION_OPEN → BREAK_EVEN → TRAILING → CLOSED,
mirroring the OrderFlow reference's lifecycle (absorption enters, initiative
moves to break-even then trails, exhaustion/divergence exits).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tradex_domain.enums import OrderSide
from tradex_domain.strategy import Signal


class TradePhase(StrEnum):
    IDLE = "idle"
    WATCHING = "watching"
    POSITION_OPEN = "position_open"
    BREAK_EVEN = "break_even"
    TRAILING = "trailing"
    CLOSED = "closed"


@dataclass
class TradeState:
    """Mutable state for one instrument's trade idea."""

    instrument: str
    direction: OrderSide
    phase: TradePhase = TradePhase.IDLE
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trail_stop: float = 0.0
    pnl: float = 0.0
    signals: list[str] = field(default_factory=list)

    def is_long(self) -> bool:
        return self.direction is OrderSide.BUY


class OrderflowAggregator:
    """Runs the trade-lifecycle state machine per instrument."""

    def __init__(
        self,
        *,
        min_entry_strength: float = 40.0,
        exit_strength: float = 70.0,
        sl_pct: float = 0.003,
        tp_pct: float = 0.006,
    ) -> None:
        self.min_entry_strength = min_entry_strength
        self.exit_strength = exit_strength
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self._states: dict[str, TradeState] = {}

    @property
    def states(self) -> dict[str, TradeState]:
        return self._states

    def state_for(self, instrument: str) -> TradeState | None:
        return self._states.get(instrument)

    def _enter(self, signal: Signal, price: float) -> TradeState:
        state = TradeState(instrument=str(signal.instrument), direction=signal.direction)
        state.phase = TradePhase.POSITION_OPEN
        state.entry_price = price
        state.trail_stop = price
        state.signals.append(signal.reason)
        if signal.direction is OrderSide.BUY:
            state.stop_loss = price * (1 - self.sl_pct)
            state.take_profit = price * (1 + self.tp_pct)
        else:
            state.stop_loss = price * (1 + self.sl_pct)
            state.take_profit = price * (1 - self.tp_pct)
        self._states[state.instrument] = state
        return state

    def on_signal(self, signal: Signal, price: float) -> TradeState:
        """Advance the state machine on a detector signal; returns the state."""
        key = str(signal.instrument)
        state = self._states.get(key)

        if state is None:
            # Absorption enters; sweep alerts only; others ignored without an idea.
            if signal.reason == "absorption" and signal.strength >= self.min_entry_strength:
                return self._enter(signal, price)
            watch = TradeState(instrument=key, direction=signal.direction)
            watch.phase = TradePhase.WATCHING
            watch.signals.append(signal.reason)
            self._states[key] = watch
            return watch

        if state.phase in (TradePhase.WATCHING, TradePhase.POSITION_OPEN):
            if signal.reason == "absorption" and signal.strength >= self.min_entry_strength:
                if state.phase is TradePhase.WATCHING:
                    self._enter(signal, price)
                    return self._states[key]
                return state
            if (
                signal.reason == "initiative"
                and signal.direction is state.direction
                and state.phase is TradePhase.POSITION_OPEN
            ):
                state.phase = TradePhase.BREAK_EVEN
                state.stop_loss = state.entry_price
                state.trail_stop = state.entry_price
                state.signals.append(signal.reason)
                return state

        if state.phase in (TradePhase.BREAK_EVEN, TradePhase.TRAILING):
            if signal.reason == "initiative" and signal.direction is state.direction:
                state.phase = TradePhase.TRAILING
                if state.is_long():
                    state.trail_stop = max(state.trail_stop, price)
                else:
                    state.trail_stop = min(state.trail_stop, price)
                state.stop_loss = state.trail_stop
                state.signals.append(signal.reason)
                return state
            if (
                signal.reason in ("exhaustion", "divergence")
                and signal.direction is not state.direction
                and signal.strength >= self.exit_strength
            ):
                self._close(state, price, signal.reason)
                return state

        return state

    def on_price(self, instrument: str, price: float) -> TradeState | None:
        """Check SL/TP/trail against a new price; returns state on a close."""
        state = self._states.get(instrument)
        if state is None or state.phase not in (
            TradePhase.POSITION_OPEN,
            TradePhase.BREAK_EVEN,
            TradePhase.TRAILING,
        ):
            return None
        if state.is_long():
            if price <= state.stop_loss or price >= state.take_profit:
                self._close(state, price, "sl_tp")
                return state
        else:
            if price >= state.stop_loss or price <= state.take_profit:
                self._close(state, price, "sl_tp")
                return state
        return None

    def _close(self, state: TradeState, price: float, reason: str) -> None:
        state.pnl = (price - state.entry_price) if state.is_long() else (
            state.entry_price - price
        )
        state.signals.append(reason)
        state.phase = TradePhase.CLOSED

    def reset(self, instrument: str | None = None) -> None:
        if instrument is None:
            self._states.clear()
        else:
            self._states.pop(instrument, None)


__all__ = ["OrderflowAggregator", "TradePhase", "TradeState"]
