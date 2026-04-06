"""
Pyramid manager — structured add-on to winning positions.

Max 2 adds (3 total entries).
Aggression ≥ 3.0 required.
Decreasing size: 100%, 50% of base.
"""

from dataclasses import dataclass
from typing import List, Optional

from src.config.engine_config import CFG


@dataclass
class PyramidSignal:
    """Pyramid add signal."""

    size_multiplier: float  # 1.0 for first add, 0.5 for second
    level: float  # Entry level for the add
    unified_sl: float  # New unified stop loss


class PyramidManager:
    """
    Structured pyramid adds per FR-09.

    Max 2 adds, aggression gate, decreasing sizing.
    """

    def __init__(self):
        self._add_count: int = 0

    def check_pyramid(
        self,
        entry_price: float,
        current_price: float,
        current_stop: float,
        direction: str,
        aggression_score: float,
        lvns: List[float],
        tick_size: float,
    ) -> Optional[PyramidSignal]:
        """
        Check if pyramid add is eligible.

        Args:
            entry_price: Original entry price
            current_price: Current market price
            current_stop: Current stop loss
            direction: Trade direction
            aggression_score: Current aggression score
            lvns: List of LVN prices
            tick_size: Instrument tick size

        Returns:
            PyramidSignal if eligible, otherwise None.
        """
        # Check max adds
        if self._add_count >= CFG.max_pyramid_adds:
            return None

        # Must be in profit
        if direction == "LONG":
            if current_price <= entry_price:
                return None
        else:
            if current_price >= entry_price:
                return None

        # Must have aggression ≥ 3.0
        if aggression_score < CFG.pyramid_aggression_score:
            return None

        # Must be at different LVN from entry
        if not self._at_new_lvn(current_price, entry_price, lvns, tick_size):
            return None

        # Determine size
        if self._add_count == 0:
            size_multiplier = CFG.pyramid_add1_size
        else:
            size_multiplier = CFG.pyramid_add2_size

        # Calculate unified stop loss
        unified_sl = self._compute_unified_sl(
            current_price, current_stop, direction, tick_size
        )

        # Increment add count
        self._add_count += 1

        return PyramidSignal(
            size_multiplier=size_multiplier,
            level=current_price,
            unified_sl=unified_sl,
        )

    def _at_new_lvn(
        self,
        current_price: float,
        entry_price: float,
        lvns: List[float],
        tick_size: float,
    ) -> bool:
        """
        Check if current price is at a different LVN from entry.
        """
        proximity = CFG.pyramid_proximity_ticks * tick_size

        for lvn in lvns:
            # Check if current price is near this LVN
            if abs(current_price - lvn) <= proximity:
                # Check if entry was NOT near this LVN
                if abs(entry_price - lvn) > proximity:
                    return True

        return False

    def _compute_unified_sl(
        self,
        new_entry: float,
        existing_sl: float,
        direction: str,
        tick_size: float,
    ) -> float:
        """
        Compute unified stop loss after pyramid add.

        Move ALL stops to latest entry SL.
        """
        buffer = tick_size * 2

        if direction == "LONG":
            # SL below new entry
            new_sl = new_entry - buffer
            # Use the higher of existing and new SL
            return max(existing_sl, new_sl)
        else:
            # SL above new entry
            new_sl = new_entry + buffer
            # Use the lower of existing and new SL
            return min(existing_sl, new_sl)

    def reset(self) -> None:
        """Reset for new trade."""
        self._add_count = 0