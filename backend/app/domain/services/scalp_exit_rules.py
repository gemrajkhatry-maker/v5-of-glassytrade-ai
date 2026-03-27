"""Scalp Exit Rules — S-EXIT-1 to S-EXIT-6.

Dedicated exit logic for scalp positions. Scalp exits are independent
of structural exits (trade_manager.py handles those).

S-EXIT-1: Hard stop at 1 tick beyond VWAP (or structural level, whichever is tighter)
S-EXIT-2: Move SL to entry + slippage after reaching 1:1 risk:reward
S-EXIT-3: Full exit if 1-min CVD flips against position direction
S-EXIT-4: Full exit if opposing absorption detected at current price
S-EXIT-5: Partial exit at target (50% size), trail remainder
S-EXIT-6: Time stop — exit after 12 bars (60 min) if neither target nor SL hit

Active rule depends on position state:
  Pre-1:1 → S-EXIT-1, S-EXIT-3, S-EXIT-4, S-EXIT-6
  Post-1:1 → S-EXIT-2, S-EXIT-3, S-EXIT-4, S-EXIT-5, S-EXIT-6
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ScalpExitAction(str, Enum):
    HOLD = "HOLD"
    TRAIL_TO_BREAKEVEN = "TRAIL_TO_BREAKEVEN"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    FULL_EXIT = "FULL_EXIT"
    TRAIL_UP = "TRAIL_UP"


@dataclass(frozen=True)
class ScalpExitResult:
    """Result of scalp exit evaluation."""

    action: ScalpExitAction
    rule: str  # S-EXIT-1 to S-EXIT-6
    reason: str
    exit_price: float  # target price for exit
    exit_size: float  # size to exit (fraction of position)
    new_stop_loss: float  # new SL after trailing


class ScalpExitEngine:
    """Evaluates scalp exit rules for a position.

    Called on every tick. Returns exit action if any rule triggers.
    """

    def __init__(
        self,
        tick_size: float = 0.05,
        slippage_ticks: int = 1,
        time_stop_bars: int = 12,
        partial_exit_pct: float = 0.50,
        breakeven_buffer_ticks: int = 1,
    ) -> None:
        self._tick_size = tick_size
        self._slippage_ticks = slippage_ticks
        self._time_stop_bars = time_stop_bars
        self._partial_exit_pct = partial_exit_pct
        self._breakeven_buffer = breakeven_buffer_ticks

    def evaluate(
        self,
        side: str,  # "BUY" or "SELL"
        entry_price: float,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        current_sl: float,
        position_size: float,
        entry_time: str,
        current_time: str,
        cvd_slope_1m: float,
        opposing_absorption: bool,
        bar_count: int,
        partial_done: bool = False,
    ) -> ScalpExitResult:
        """Evaluate all scalp exit rules. First trigger wins."""

        risk = abs(entry_price - stop_loss) if stop_loss != entry_price else 1.0
        is_long = side == "BUY"
        unrealized_r = (
            (current_price - entry_price) / risk
            if is_long
            else (entry_price - current_price) / risk
        )

        # ── S-EXIT-1: Hard stop ──
        if is_long and current_price <= current_sl:
            return ScalpExitResult(
                action=ScalpExitAction.FULL_EXIT,
                rule="S-EXIT_1",
                reason=f"Hard stop hit: price {current_price} <= SL {current_sl}",
                exit_price=current_price,
                exit_size=1.0,
                new_stop_loss=current_sl,
            )
        if not is_long and current_price >= current_sl:
            return ScalpExitResult(
                action=ScalpExitAction.FULL_EXIT,
                rule="S-EXIT_1",
                reason=f"Hard stop hit: price {current_price} >= SL {current_sl}",
                exit_price=current_price,
                exit_size=1.0,
                new_stop_loss=current_sl,
            )

        # ── S-EXIT-6: Time stop ──
        if bar_count >= self._time_stop_bars:
            return ScalpExitResult(
                action=ScalpExitAction.FULL_EXIT,
                rule="S-EXIT_6",
                reason=f"Time stop: {bar_count} bars elapsed (limit={self._time_stop_bars})",
                exit_price=current_price,
                exit_size=1.0,
                new_stop_loss=current_sl,
            )

        # ── S-EXIT-3: CVD flip ──
        if is_long and cvd_slope_1m < -15:
            return ScalpExitResult(
                action=ScalpExitAction.FULL_EXIT,
                rule="S-EXIT_3",
                reason=f"CVD flip against LONG: slope={cvd_slope_1m:.1f}",
                exit_price=current_price,
                exit_size=1.0,
                new_stop_loss=current_sl,
            )
        if not is_long and cvd_slope_1m > 15:
            return ScalpExitResult(
                action=ScalpExitAction.FULL_EXIT,
                rule="S-EXIT_3",
                reason=f"CVD flip against SHORT: slope={cvd_slope_1m:.1f}",
                exit_price=current_price,
                exit_size=1.0,
                new_stop_loss=current_sl,
            )

        # ── S-EXIT-4: Opposing absorption ──
        if opposing_absorption:
            return ScalpExitResult(
                action=ScalpExitAction.FULL_EXIT,
                rule="S-EXIT_4",
                reason="Opposing absorption detected at current price",
                exit_price=current_price,
                exit_size=1.0,
                new_stop_loss=current_sl,
            )

        # ── Post-1:1 rules ──
        if unrealized_r >= 1.0:
            # S-EXIT-2: Move SL to entry + slippage buffer
            breakeven_sl = (
                entry_price + self._breakeven_buffer * self._tick_size
                if is_long
                else entry_price - self._breakeven_buffer * self._tick_size
            )
            if current_sl != breakeven_sl:
                return ScalpExitResult(
                    action=ScalpExitAction.TRAIL_TO_BREAKEVEN,
                    rule="S-EXIT_2",
                    reason=f"1:1 reached (R={unrealized_r:.1f}), trailing SL to breakeven",
                    exit_price=0,
                    exit_size=0,
                    new_stop_loss=breakeven_sl,
                )

            # S-EXIT-5: Partial exit at 1.5R (if not done)
            if unrealized_r >= 1.5 and not partial_done:
                return ScalpExitResult(
                    action=ScalpExitAction.PARTIAL_EXIT,
                    rule="S-EXIT_5",
                    reason=f"Partial exit at R={unrealized_r:.1f} (50% size)",
                    exit_price=current_price,
                    exit_size=self._partial_exit_pct,
                    new_stop_loss=breakeven_sl,
                )

            # Trail remaining position
            if partial_done:
                trail_price = (
                    entry_price + unrealized_r * risk * 0.5
                    if is_long
                    else entry_price - unrealized_r * risk * 0.5
                )
                if (is_long and trail_price > current_sl) or (
                    not is_long and trail_price < current_sl
                ):
                    return ScalpExitResult(
                        action=ScalpExitAction.TRAIL_UP,
                        rule="S-EXIT_5",
                        reason=f"Trailing: R={unrealized_r:.1f}",
                        exit_price=0,
                        exit_size=0,
                        new_stop_loss=trail_price,
                    )

        return ScalpExitResult(
            action=ScalpExitAction.HOLD,
            rule="",
            reason="",
            exit_price=0,
            exit_size=0,
            new_stop_loss=current_sl,
        )
