"""Rule-based exit engine: SL, TP, CVD-kill, and time-stop.

Pure and deterministic. No imports from backend/ or app/.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant.auction_state import AuctionState
from quant.execution.order import Position


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str          # "" | "SL" | "TP" | "TRAIL" | "TIME" | "CVD_KILL"
    close_price: float
    trail_stop: float | None = None


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

    def __init__(self, time_stop_bars: int = 30, cvd_kill_threshold: float = float("inf")) -> None:
        self.time_stop_bars = time_stop_bars
        self.cvd_kill_threshold = cvd_kill_threshold

    def evaluate(
        self,
        position: Position,
        state: AuctionState,
        bar_index: int,
        bar_high: float | None = None,
        bar_low: float | None = None,
    ) -> ExitDecision:
        close = float(state.close)
        long = position.size > 0
        sl = float(position.order.signal.sl)
        tp = float(position.order.signal.tp)
        low = close if bar_low is None else bar_low
        high = close if bar_high is None else bar_high

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

        if bar_index >= self.time_stop_bars:
            return ExitDecision(True, "TIME", close)

        return ExitDecision(False, "", close)
