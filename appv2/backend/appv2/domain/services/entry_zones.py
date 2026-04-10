"""Entry Zones — identifies optimal entry zones from AMT levels.

Three entry zone types:
1. VA Edge Pullback — price pulls back to VAH/VAL after breakout
2. LVN Retest — price retests a Low Volume Node
3. POC Bounce — price bounces off Point of Control
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryZone:
    zone_type: str  # "VA_EDGE" | "LVN_RETEST" | "POC_BOUNCE"
    price: float  # Target entry price
    tolerance: float  # ± tolerance for entry
    direction: str  # "LONG" | "SHORT"
    confidence: float  # 0.0-1.0
    reason: str


class EntryZoneDetector:
    """Identifies optimal entry zones from AMT levels."""

    def __init__(self, tick_size: float = 0.05):
        self._tick_size = tick_size

    def va_edge_pullback(
        self,
        direction: str,
        current_price: float,
        vah: float,
        val: float,
        poc: float,
        is_after_break: bool = False,
    ) -> EntryZone | None:
        """Detect VA edge pullback entry.

        LONG: Price broke above VAH and pulled back to VAH ± tolerance
        SHORT: Price broke below VAL and pulled back to VAL ± tolerance
        """
        tolerance = self._tick_size * 5  # ±5 ticks

        if direction == "LONG":
            if vah > 0 and abs(current_price - vah) <= tolerance:
                if is_after_break or current_price > poc:
                    return EntryZone(
                        zone_type="VA_EDGE",
                        price=vah,
                        tolerance=tolerance,
                        direction="LONG",
                        confidence=0.75,
                        reason=f"Pullback to VAH ({vah:.2f})",
                    )
        else:
            if val > 0 and abs(current_price - val) <= tolerance:
                if is_after_break or current_price < poc:
                    return EntryZone(
                        zone_type="VA_EDGE",
                        price=val,
                        tolerance=tolerance,
                        direction="SHORT",
                        confidence=0.75,
                        reason=f"Pullback to VAL ({val:.2f})",
                    )

        return None

    def lvn_retest(
        self,
        direction: str,
        current_price: float,
        lvn_levels: list[float],
        tolerance_ticks: int = 3,
    ) -> EntryZone | None:
        """Detect LVN retest entry.

        Price approaches a Low Volume Node — fast movement expected.
        """
        tolerance = self._tick_size * tolerance_ticks

        for lvn in sorted(lvn_levels):
            if abs(current_price - lvn) <= tolerance:
                # LONG: approaching LVN from below (expect fast move through)
                if direction == "LONG" and current_price <= lvn + tolerance:
                    return EntryZone(
                        zone_type="LVN_RETEST",
                        price=lvn,
                        tolerance=tolerance,
                        direction="LONG",
                        confidence=0.65,
                        reason=f"LVN retest at {lvn:.2f}",
                    )
                # SHORT: approaching LVN from above
                elif direction == "SHORT" and current_price >= lvn - tolerance:
                    return EntryZone(
                        zone_type="LVN_RETEST",
                        price=lvn,
                        tolerance=tolerance,
                        direction="SHORT",
                        confidence=0.65,
                        reason=f"LVN retest at {lvn:.2f}",
                    )

        return None

    def poc_bounce(
        self,
        direction: str,
        current_price: float,
        poc: float,
        vah: float,
        val: float,
        tolerance_ticks: int = 3,
    ) -> EntryZone | None:
        """Detect POC bounce entry.

        Price approaches POC from above/below — expect bounce.
        """
        tolerance = self._tick_size * tolerance_ticks

        if poc <= 0:
            return None

        if direction == "LONG":
            # Price coming down to POC from above
            if current_price >= poc and current_price <= poc + tolerance:
                if current_price > val:  # Still above VAL
                    return EntryZone(
                        zone_type="POC_BOUNCE",
                        price=poc,
                        tolerance=tolerance,
                        direction="LONG",
                        confidence=0.60,
                        reason=f"POC bounce at {poc:.2f}",
                    )
        else:
            # Price coming up to POC from below
            if current_price <= poc and current_price >= poc - tolerance:
                if current_price < vah:  # Still below VAH
                    return EntryZone(
                        zone_type="POC_BOUNCE",
                        price=poc,
                        tolerance=tolerance,
                        direction="SHORT",
                        confidence=0.60,
                        reason=f"POC bounce at {poc:.2f}",
                    )

        return None

    def find_best_zone(
        self,
        direction: str,
        current_price: float,
        poc: float,
        vah: float,
        val: float,
        lvn_levels: list[float] | None = None,
        is_after_break: bool = False,
    ) -> EntryZone | None:
        """Find the best entry zone across all types.

        Priority: VA Edge > LVN Retest > POC Bounce
        """
        # 1. VA Edge Pullback (highest confidence)
        zone = self.va_edge_pullback(direction, current_price, vah, val, poc, is_after_break)
        if zone:
            return zone

        # 2. LVN Retest
        if lvn_levels:
            zone = self.lvn_retest(direction, current_price, lvn_levels)
            if zone:
                return zone

        # 3. POC Bounce
        zone = self.poc_bounce(direction, current_price, poc, vah, val)
        if zone:
            return zone

        return None
