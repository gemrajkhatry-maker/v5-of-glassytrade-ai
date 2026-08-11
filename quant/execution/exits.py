"""Rule-based exit engine: spread blowout, SL, TP, CVD-kill, trailing, and time-stop.

Pure and deterministic. No imports from backend/ or app/.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant.auction_state import AuctionState
from quant.execution.exit_rules import get_session_time_stop
from quant.execution.order import Position


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str          # "" | "SL" | "TP" | "TRAIL" | "TIME" | "CVD_KILL" | "SPREAD_BLOWOUT"
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
        trail_giveback_pct: float = 0.30,
        spread_max_pct: float = 0.03,
    ) -> None:
        self.time_stop_bars = time_stop_bars
        self.cvd_kill_threshold = cvd_kill_threshold
        self.trail_giveback_pct = trail_giveback_pct
        self.spread_max_pct = spread_max_pct
        # Trailing state is keyed by id(position) because Position is frozen.
        self._trail: dict[int, _Trail] = {}

    def pop_trail(self, position: Position) -> None:
        """Drop trailing state for a closed position."""
        self._trail.pop(id(position), None)

    def evaluate(
        self,
        position: Position,
        state: AuctionState,
        bar_index: int,
        bar_high: float | None = None,
        bar_low: float | None = None,
        *,
        best_bid: float | None = None,
        best_ask: float | None = None,
        market_state: str = "",
        session_phase: str = "",
        is_expiry: bool = False,
        time_to_close: float = 0.0,
        entry_time_epoch: float = 0.0,
        now_epoch: float = 0.0,
    ) -> ExitDecision:
        close = float(state.close)
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

        slope = float(state.order_flow.cvd_slope)
        if long and slope < -self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)
        if not long and slope > self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)

        # 4. Trailing stop — only once the trade has reached 1R profit.
        entry = float(position.order.signal.entry)
        risk = abs(entry - sl)
        if risk > 0:
            profit = (close - entry) if long else (entry - close)
            if profit >= risk:
                tr = self._trail.setdefault(id(position), _Trail())
                tr.active = True
                candidate = (
                    close - self.trail_giveback_pct * profit
                    if long
                    else close + self.trail_giveback_pct * profit
                )
                # Never loosen below the original stop-loss.
                candidate = max(candidate, sl) if long else min(candidate, sl)
                if tr.stop is None:
                    tr.stop = candidate
                else:
                    # Monotonicity: long trails only rise, short only fall.
                    tr.stop = max(tr.stop, candidate) if long else min(tr.stop, candidate)
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
