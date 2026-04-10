"""Structural Stop Engine — places SL beyond aggressive print levels.

Fabio's SL placement rules:
- LONG: Just below the nearest aggressive sell print / absorption area
- SHORT: Just above the nearest aggressive buy print / absorption area
- Buffer: 1-2 ticks beyond the level
- NEVER widen SL — invalidation is instant

Uses footprint data to find the exact level where aggressive orders appeared.
"""

from __future__ import annotations

from dataclasses import dataclass
from appv2.domain.services.footprint_accumulator import FootprintCandle


@dataclass(frozen=True)
class StructuralStop:
    price: float
    level_type: str  # "AGGRESSIVE_PRINT" | "ABSORPTION" | "HVN" | "LVN"
    distance_from_entry: float
    risk_per_unit: float
    confidence: float


class StructuralStopEngine:
    """Calculates structural stop-loss levels from order flow data."""

    def __init__(self, tick_size: float = 0.05, buffer_ticks: int = 2):
        self._tick_size = tick_size
        self._buffer = buffer_ticks * tick_size

    def calculate_stop(
        self,
        direction: str,
        entry_price: float,
        footprint: FootprintCandle | None,
        aggressive_levels: list[float] | None = None,
        lvn_levels: list[float] | None = None,
        vah: float = 0.0,
        val: float = 0.0,
        poc: float = 0.0,
    ) -> StructuralStop:
        """Calculate structural stop-loss level.

        Args:
            direction: "LONG" or "SHORT"
            entry_price: Entry price
            footprint: Current candle footprint
            aggressive_levels: Known aggressive print prices
            lvn_levels: Low Volume Node prices
            vah/val/poc: Volume Profile levels

        Returns:
            StructuralStop with price and metadata
        """
        # Priority 1: Footprint-based stops
        if footprint:
            stop = self._from_footprint(direction, entry_price, footprint)
            if stop:
                return stop

        # Priority 2: Aggressive print levels
        if aggressive_levels:
            stop = self._from_aggressive(
                direction, entry_price, aggressive_levels
            )
            if stop:
                return stop

        # Priority 3: LVN-based stops
        if lvn_levels:
            stop = self._from_lvn(direction, entry_price, lvn_levels)
            if stop:
                return stop

        # Priority 4: VA-based stops
        stop = self._from_va(direction, entry_price, vah, val, poc)
        if stop:
            return stop

        # Fallback: Fixed distance from entry
        buffer = self._buffer
        if direction == "LONG":
            sl_price = entry_price - buffer * 3
        else:
            sl_price = entry_price + buffer * 3

        return StructuralStop(
            price=sl_price,
            level_type="FIXED_BUFFER",
            distance_from_entry=abs(entry_price - sl_price),
            risk_per_unit=abs(entry_price - sl_price),
            confidence=0.3,
        )

    def _from_footprint(
        self, direction: str, entry: float, footprint: FootprintCandle
    ) -> StructuralStop | None:
        """Find stop from footprint imbalances."""
        if direction == "LONG":
            # Look for aggressive selling (bid volume) below entry
            below_entry = [
                lv for lv in footprint.levels if lv.price < entry
            ]
            if below_entry:
                # Find the level with max bid volume (strongest selling)
                strongest = max(below_entry, key=lambda lv: lv.bid_volume)
                sl_price = strongest.price - self._buffer
                return StructuralStop(
                    price=sl_price,
                    level_type="AGGRESSIVE_PRINT",
                    distance_from_entry=entry - sl_price,
                    risk_per_unit=entry - sl_price,
                    confidence=0.8 if strongest.is_imbalance else 0.6,
                )
        else:  # SHORT
            # Look for aggressive buying (ask volume) above entry
            above_entry = [
                lv for lv in footprint.levels if lv.price > entry
            ]
            if above_entry:
                strongest = max(above_entry, key=lambda lv: lv.ask_volume)
                sl_price = strongest.price + self._buffer
                return StructuralStop(
                    price=sl_price,
                    level_type="AGGRESSIVE_PRINT",
                    distance_from_entry=sl_price - entry,
                    risk_per_unit=sl_price - entry,
                    confidence=0.8 if strongest.is_imbalance else 0.6,
                )
        return None

    def _from_aggressive(
        self, direction: str, entry: float, levels: list[float]
    ) -> StructuralStop | None:
        """Find stop from known aggressive print levels."""
        if direction == "LONG":
            below = [lv for lv in levels if lv < entry]
            if below:
                nearest = max(below)
                sl = nearest - self._buffer
                return StructuralStop(
                    price=sl,
                    level_type="AGGRESSIVE_PRINT",
                    distance_from_entry=entry - sl,
                    risk_per_unit=entry - sl,
                    confidence=0.7,
                )
        else:
            above = [lv for lv in levels if lv > entry]
            if above:
                nearest = min(above)
                sl = nearest + self._buffer
                return StructuralStop(
                    price=sl,
                    level_type="AGGRESSIVE_PRINT",
                    distance_from_entry=sl - entry,
                    risk_per_unit=sl - entry,
                    confidence=0.7,
                )
        return None

    def _from_lvn(
        self, direction: str, entry: float, levels: list[float]
    ) -> StructuralStop | None:
        """Find stop from LVN levels (acceleration zones)."""
        if direction == "LONG":
            below = [lv for lv in levels if lv < entry]
            if below:
                nearest = max(below)
                sl = nearest - self._buffer
                return StructuralStop(
                    price=sl,
                    level_type="LVN",
                    distance_from_entry=entry - sl,
                    risk_per_unit=entry - sl,
                    confidence=0.5,
                )
        else:
            above = [lv for lv in levels if lv > entry]
            if above:
                nearest = min(above)
                sl = nearest + self._buffer
                return StructuralStop(
                    price=sl,
                    level_type="LVN",
                    distance_from_entry=sl - entry,
                    risk_per_unit=sl - entry,
                    confidence=0.5,
                )
        return None

    def _from_va(
        self, direction: str, entry: float, vah: float, val: float, poc: float
    ) -> StructuralStop | None:
        """Find stop from Value Area levels."""
        if direction == "LONG":
            if val > 0 and val < entry:
                sl = val - self._buffer
                return StructuralStop(
                    price=sl,
                    level_type="HVN",
                    distance_from_entry=entry - sl,
                    risk_per_unit=entry - sl,
                    confidence=0.6,
                )
        else:
            if vah > 0 and vah > entry:
                sl = vah + self._buffer
                return StructuralStop(
                    price=sl,
                    level_type="HVN",
                    distance_from_entry=sl - entry,
                    risk_per_unit=sl - entry,
                    confidence=0.6,
                )
        return None
