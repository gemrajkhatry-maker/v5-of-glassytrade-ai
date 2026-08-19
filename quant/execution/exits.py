"""Rule-based exit engine: spread blowout, SL, TP, CVD-kill, trailing, and time-stop.

Pure and deterministic. No imports from backend/ or app/.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

from dataclasses import dataclass


from quant.execution.exit_rules import get_session_time_stop
from quant.execution.order import Position


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str          # "" | "SL" | "TP" | "TRAIL" | "TIME" | "CVD_KILL" | "SPREAD_BLOWOUT" | "BREAKEVEN"
    close_price: float
    trail_stop: float | None = None


@dataclass
class _Trail:
    active: bool = False
    stop: float | None = None


class ExitEngine:
    """Rule-based exit engine.

    CVD_KILL semantics: a kill fires only when the cvd slope crosses the
    adverse side of a NEGATIVE threshold, i.e. LONG exits when
    ``cvd_slope < -threshold`` and SHORT exits when ``cvd_slope > threshold``.
    A positive threshold therefore never kills on a favorable-side slope.
    Default ``cvd_kill_threshold=float("inf")`` disables CVD_KILL entirely
    unless it is explicitly enabled (threshold=0.0 would kill on ANY adverse
    slope, which is too twitchy for noise).
    """

    def __init__(
        self,
        time_stop_bars: int = 30,
        cvd_kill_threshold: float = float("inf"),
        trail_giveback_pct: float = 0.20,
        spread_max_pct: float = 0.03,
        cvd_be_threshold: float = 2.0,
    ) -> None:
        self.time_stop_bars = time_stop_bars
        self.cvd_kill_threshold = cvd_kill_threshold
        self.trail_giveback_pct = trail_giveback_pct
        self.spread_max_pct = spread_max_pct
        self.cvd_be_threshold = cvd_be_threshold
        # Trailing state is keyed by id(position) because Position is frozen.
        self._trail: dict[int, _Trail] = {}
        self._breakeven: dict[int, float | None] = {}  # id(position) -> BE floor price

    def pop_trail(self, position: Position) -> None:
        """Drop trailing state for a closed position."""
        self._trail.pop(id(position), None)
        self._breakeven.pop(id(position), None)

    def is_risk_free(self, position: Position) -> bool:
        """Return True when this position has reached the 0.8R breakeven floor.

        Used by the pyramid engine to authorize add-ons: per spec §13.2 the
        base trade must be risk-free (SL at entry or better) before any
        pyramid entry is permitted.
        """
        be_floor = self._breakeven.get(id(position))
        return be_floor is not None

    def evaluate(
        self,
        position: Position,
        state: dict | float | None = None,
        bar_index: int = 0,
        bar_high: float | None = None,
        bar_low: float | None = None,
        *,
        amt_dto: dict | None = None,
        best_bid: float | None = None,
        best_ask: float | None = None,
        market_state: MarketState = MarketState.BALANCED,
        session_phase: str = "",
        is_expiry: bool = False,
        time_to_close: float = 0.0,
        entry_time_epoch: float = 0.0,
        now_epoch: float = 0.0,
        bar_close: float | None = None,
    ) -> ExitDecision:
        if bar_close is not None:
            close = float(bar_close)
        elif isinstance(state, (int, float)):
            close = float(state)
            state = None
        else:
            close = 0.0

        dto = amt_dto or (state if isinstance(state, dict) else {})
        long = position.size > 0
        sl = float(position.order.signal.sl)
        tp = float(position.order.signal.tp)
        low = close if bar_low is None else bar_low
        high = close if bar_high is None else bar_high

        # 1. Spread blowout — the book is untradeable, get out at mid.
        if (
            best_bid is not None
            and best_ask is not None
            and close > 0
            and (best_ask - best_bid) / close >= self.spread_max_pct
        ):
            return ExitDecision(True, "SPREAD_BLOWOUT", (best_bid + best_ask) / 2)

        if long and low <= sl:
            return ExitDecision(True, "SL", close)
        if not long and high >= sl:
            return ExitDecision(True, "SL", close)

        if long and high >= tp:
            return ExitDecision(True, "TP", close)
        if not long and low <= tp:
            return ExitDecision(True, "TP", close)

        slope = float(dto.get("cvdSlope") or 0.0)
        if long and slope < -self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)
        if not long and slope > self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)

        # 3b. Breakeven logic — Fabio: move SL to entry at 1R or on CVD confirmation.
        # The breakeven floor ensures the trail can never drop below entry once armed.
        entry = float(position.order.signal.entry)
        risk = abs(entry - sl)
        be_floor = self._breakeven.get(id(position))

        if risk > 0:
            profit = (close - entry) if long else (entry - close)
            
            # CVD-based early breakeven: if profit > 0 and CVD slope strongly
            # confirms direction, lock in breakeven immediately (Fabio Gap #5).
            cvd_slope = float(dto.get("cvdSlope") or 0.0)
            if be_floor is None and profit > 0:
                cvd_confirms = (
                    (long and cvd_slope > self.cvd_be_threshold)
                    or (not long and cvd_slope < -self.cvd_be_threshold)
                )
                if cvd_confirms:
                    be_floor = entry
                    self._breakeven[id(position)] = be_floor
            
            # Standard 0.8R breakeven: once profit reaches 0.8R, floor at entry.
            # Spec §13.1: "Price breaks +0.8R advance → SL ← entry_price instantly."
            # Triggers before full 1R to lock in risk-free status early and enable pyramiding.
            if be_floor is None and profit >= risk * 0.8:
                be_floor = entry
                self._breakeven[id(position)] = be_floor

        # 4. Trailing stop — only once the trade has reached 1R profit.
        tr = self._trail.get(id(position))
        if risk > 0:
            # Ratchet ONLY at/above 1R; once armed, enforce on every bar so a
            # giveback below 1R can't silently ride back to the original SL.
            if profit >= risk:
                if tr is None:
                    tr = _Trail()
                    self._trail[id(position)] = tr
                tr.active = True
                candidate = (
                    close - self.trail_giveback_pct * profit
                    if long
                    else close + self.trail_giveback_pct * profit
                )
                # Never loosen below the original stop-loss.
                candidate = max(candidate, sl) if long else min(candidate, sl)
                
                # Enforce breakeven floor from step 3b
                if be_floor is not None:
                    candidate = max(candidate, be_floor) if long else min(candidate, be_floor)

                if tr.stop is None:
                    tr.stop = candidate
                else:
                    # Monotonicity: long trails only rise, short only fall.
                    tr.stop = max(tr.stop, candidate) if long else min(tr.stop, candidate)
            
            # Check breakeven stop (armed by CVD before 1R)
            if be_floor is not None and tr is None:
                if (long and low <= be_floor) or (not long and high >= be_floor):
                    return ExitDecision(True, "BREAKEVEN", close)

            if tr is not None and tr.stop is not None:
                if (long and low <= tr.stop) or (not long and high >= tr.stop):
                    return ExitDecision(True, "TRAIL", close, trail_stop=tr.stop)

        # 5. Time stop — session-aware when the context is present.
        if session_phase and time_to_close > 0 and now_epoch and entry_time_epoch:
            max_hold = get_session_time_stop(market_state, session_phase, is_expiry, time_to_close)
            if now_epoch - entry_time_epoch >= max_hold:
                return ExitDecision(True, "TIME", close)
        elif bar_index >= self.time_stop_bars:
            return ExitDecision(True, "TIME", close)

        return ExitDecision(False, "", close)
