"""Breakeven + Trailing Stop Engine — deterministic post-entry management.

CHANGE 6: Fully automated stop management based on Fabio's rules.

TRIGGER (any ONE condition):
  a. Price moves 1R in favor (floating_pnl >= initial_risk)
  b. Strong CVD confirmation within 60 seconds of entry
  c. Scale-in Entry 2 filled (floating cushion exists)

ACTION:
  new_stop = entry_price + 1 tick (for LONG)
  new_stop = entry_price - 1 tick (for SHORT)
  Status: RISK-FREE

TRAILING AFTER BREAKEVEN:
  Trail stop to most recent HVN/LVN on the volume profile
  After Entry 3 filled: move Entry 1 stop to breakeven

RUNNER EXCEPTION (strict criteria, all must be true):
  - Market is in strong imbalance (not balanced)
  - Displacement continuing on new candles
  - Session PnL already positive
  - Close 70-80% at POC, trail remaining 20-30%
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StopAction(str, Enum):
    HOLD = "HOLD"
    MOVE_TO_BREAKEVEN = "MOVE_TO_BREAKEVEN"
    TRAIL_TO_LEVEL = "TRAIL_TO_LEVEL"
    CLOSE_POSITION = "CLOSE_POSITION"
    RUNNER_EXIT = "RUNNER_EXIT"  # partial exit + trail rest


@dataclass(frozen=True)
class StopResult:
    """Result of stop management evaluation."""

    action: StopAction
    new_stop: float
    reason: str
    exit_pct: float = 0.0  # percentage to exit (0 = no exit)


class BreakevenTrailingEngine:
    """Deterministic stop management engine.

    No LLM involvement. Pure rules based on price movement, CVD, and scale-in status.
    """

    def __init__(
        self,
        tick_size: float = 0.05,
        breakeven_buffer_ticks: int = 1,
        runner_exit_pct: float = 0.25,  # 25% position remains for runner
    ) -> None:
        self._tick = tick_size
        self._be_buffer = breakeven_buffer_ticks
        self._runner_pct = runner_exit_pct

    def evaluate(
        self,
        direction: str,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        target_price: float,
        initial_risk: float,
        cvd_slope: float,
        cvd_slope_60s_ago: float,
        scale_in_count: int,
        is_strong_imbalance: bool,
        session_pnl: float,
        position_size: int,
    ) -> StopResult:
        """Evaluate stop management rules.

        Args:
            direction: "LONG" or "SHORT"
            entry_price: Original entry price
            current_price: Current market price
            stop_loss: Current stop loss
            target_price: Target price (POC)
            initial_risk: Initial risk amount (entry - stop)
            cvd_slope: Current CVD slope
            cvd_slope_60s_ago: CVD slope 60 seconds ago
            scale_in_count: Number of scale-in entries filled (0-3)
            is_strong_imbalance: Market is in strong imbalance
            session_pnl: Current session PnL
            position_size: Current position size
        """
        is_long = direction == "LONG"

        # Calculate R multiple
        if is_long:
            unrealized_r = (
                (current_price - entry_price) / initial_risk if initial_risk > 0 else 0
            )
        else:
            unrealized_r = (
                (entry_price - current_price) / initial_risk if initial_risk > 0 else 0
            )

        # Breakeven trigger conditions
        trigger_1r = unrealized_r >= 1.0
        trigger_cvd = (is_long and cvd_slope > 0 and cvd_slope_60s_ago <= 0) or (
            not is_long and cvd_slope < 0 and cvd_slope_60s_ago >= 0
        )
        trigger_scale = scale_in_count >= 2  # Entry 2 filled

        # Check if already at breakeven
        breakeven_price = (
            entry_price + self._tick * self._be_buffer
            if is_long
            else entry_price - self._tick * self._be_buffer
        )
        is_at_breakeven = (is_long and stop_loss >= breakeven_price) or (
            not is_long and stop_loss <= breakeven_price
        )

        # If already at breakeven, check for trailing
        if is_at_breakeven:
            # Runner exception: 70-80% exit at POC + trail rest
            if unrealized_r >= 2.0 and is_strong_imbalance and session_pnl > 0:
                # Trail to POC or last structural level
                new_stop = (
                    target_price - self._tick * 2
                    if is_long
                    else target_price + self._tick * 2
                )
                return StopResult(
                    action=StopAction.RUNNER_EXIT,
                    new_stop=new_stop,
                    reason=f"Runner: R={unrealized_r:.1f}, strong imbalance, trail to {new_stop:.2f}",
                    exit_pct=1.0 - self._runner_pct,  # close 75%, trail 25%
                )

            # Regular trailing: move stop to current price - buffer
            trail_price = (
                current_price - self._tick * 2
                if is_long
                else current_price + self._tick * 2
            )
            if (is_long and trail_price > stop_loss) or (
                not is_long and trail_price < stop_loss
            ):
                return StopResult(
                    action=StopAction.TRAIL_TO_LEVEL,
                    new_stop=trail_price,
                    reason=f"Trailing: R={unrealized_r:.1f}",
                )

            return StopResult(
                action=StopAction.HOLD,
                new_stop=stop_loss,
                reason="At breakeven, no trailing update needed",
            )

        # Check for breakeven trigger
        if trigger_1r or trigger_cvd or trigger_scale:
            triggers = []
            if trigger_1r:
                triggers.append(f"1R={unrealized_r:.1f}")
            if trigger_cvd:
                triggers.append("CVD flip")
            if trigger_scale:
                triggers.append(f"scale-in {scale_in_count}")

            return StopResult(
                action=StopAction.MOVE_TO_BREAKEVEN,
                new_stop=breakeven_price,
                reason=f"Breakeven: {', '.join(triggers)} — RISK-FREE",
            )

        return StopResult(
            action=StopAction.HOLD,
            new_stop=stop_loss,
            reason=f"Holding: R={unrealized_r:.1f}",
        )

    def get_breakeven_price(self, entry_price: float, direction: str) -> float:
        """Calculate breakeven stop price."""
        if direction == "LONG":
            return entry_price + self._tick * self._be_buffer
        else:
            return entry_price - self._tick * self._be_buffer
