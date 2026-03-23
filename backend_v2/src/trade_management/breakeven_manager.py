"""
Break-even manager — move SL to entry at 35% of R toward target.

Triggered when unrealized profit reaches 35% of the risk distance.
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG


@dataclass
class BreakEvenResult:
    """Break-even check result."""

    triggered: bool
    new_stop_loss: Optional[float]


class BreakEvenManager:
    """
    Break-even trigger logic per FR-08-07.

    Move stop loss to entry price when price reaches 35% of R toward target.
    """

    @staticmethod
    def check(
        entry_price: float,
        current_price: float,
        initial_stop: float,
        direction: str,
        already_set: bool = False,
    ) -> BreakEvenResult:
        """
        Check if break-even should be triggered.

        Args:
            entry_price: Entry price
            current_price: Current market price
            initial_stop: Initial stop loss
            direction: Trade direction (LONG/SHORT)
            already_set: Whether BE has already been set

        Returns:
            BreakEvenResult with trigger status and new SL.
        """
        if already_set:
            return BreakEvenResult(triggered=False, new_stop_loss=None)

        # Calculate risk
        risk = abs(entry_price - initial_stop)
        if risk <= 0:
            return BreakEvenResult(triggered=False, new_stop_loss=None)

        # Calculate unrealized
        if direction == "LONG":
            unrealized = current_price - entry_price
        else:
            unrealized = entry_price - current_price

        # Check if 35% of R reached
        trigger_threshold = risk * CFG.breakeven_trigger_r

        if unrealized >= trigger_threshold:
            # Move SL to entry
            return BreakEvenResult(triggered=True, new_stop_loss=entry_price)

        return BreakEvenResult(triggered=False, new_stop_loss=None)