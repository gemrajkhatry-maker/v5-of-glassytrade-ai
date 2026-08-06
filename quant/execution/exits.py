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
    def __init__(self, time_stop_bars: int = 30, cvd_kill_threshold: float = 0.0) -> None:
        self.time_stop_bars = time_stop_bars
        self.cvd_kill_threshold = cvd_kill_threshold

    def evaluate(self, position: Position, state: AuctionState, bar_index: int) -> ExitDecision:
        close = float(state.close)
        long = position.size > 0
        sl = float(position.order.signal.sl)
        tp = float(position.order.signal.tp)

        if long and close <= sl:
            return ExitDecision(True, "SL", close)
        if not long and close >= sl:
            return ExitDecision(True, "SL", close)

        if long and close >= tp:
            return ExitDecision(True, "TP", close)
        if not long and close <= tp:
            return ExitDecision(True, "TP", close)

        slope = float(state.order_flow.cvd_slope)
        if long and slope < self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)
        if not long and slope > -self.cvd_kill_threshold:
            return ExitDecision(True, "CVD_KILL", close)

        if bar_index >= self.time_stop_bars:
            return ExitDecision(True, "TIME", close)

        return ExitDecision(False, "", close)
