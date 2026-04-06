"""
Leg anchor — detect leg start and reset logic.

Leg = price movement from VA break to extreme (impulse leg).
Auto-detects leg start on displacement + volume confirmation.
Auto-resets when price re-enters value area.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.config.engine_config import CFG
from src.core.candle_builder import Candle


@dataclass
class LegAnchor:
    """Leg anchor state."""

    start_price: float
    start_time: datetime
    direction: str  # "LONG" or "SHORT"
    extreme_price: float  # Current extreme (highest for LONG, lowest for SHORT)
    candle_count: int = 0


class LegAnchorDetector:
    """
    Detect leg starts and manage leg reset logic.

    Leg starts when price breaks VA with displacement + volume.
    Leg resets when price re-enters value area.
    """

    @staticmethod
    def detect_leg_start(
        price: float,
        vah: Optional[float],
        val: Optional[float],
        candle: Candle,
        avg_vol: float,
        atr: float,
    ) -> Optional[LegAnchor]:
        """
        Detect if a new leg is starting.

        Conditions:
        1. Price breaks VAH or VAL
        2. Displacement candle (range > ATR × 1.5)
        3. Volume > avg × 1.5

        Returns LegAnchor if leg starts, otherwise None.
        """
        if vah is None or val is None:
            return None

        # Check for VA break
        breaks_vah = price > vah
        breaks_val = price < val

        if not (breaks_vah or breaks_val):
            return None

        # Check displacement
        candle_range = candle.high - candle.low
        has_displacement = candle_range > atr * CFG.displacement_multiplier

        # Check volume
        has_volume = candle.volume > avg_vol * 1.5

        if not (has_displacement and has_volume):
            return None

        # Determine direction
        direction = "LONG" if breaks_vah else "SHORT"
        extreme = price

        return LegAnchor(
            start_price=price,
            start_time=candle.candle_start,
            direction=direction,
            extreme_price=extreme,
            candle_count=1,
        )

    @staticmethod
    def should_reset_leg(
        price: float,
        val: Optional[float],
        vah: Optional[float],
        current_anchor: Optional[LegAnchor],
    ) -> bool:
        """
        Check if leg should reset (price re-enters value area).

        Returns True if leg should be cleared.
        """
        if current_anchor is None:
            return False

        if val is None or vah is None:
            return False

        # Reset if price re-enters value area
        in_value_area = val <= price <= vah
        return in_value_area

    @staticmethod
    def update_extreme(
        anchor: LegAnchor,
        price: float,
    ) -> None:
        """Update the leg extreme price."""
        if anchor.direction == "LONG":
            anchor.extreme_price = max(anchor.extreme_price, price)
        else:
            anchor.extreme_price = min(anchor.extreme_price, price)

        anchor.candle_count += 1