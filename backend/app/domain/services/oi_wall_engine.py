"""OI Wall Engine — Detects high Open Interest strikes as protection levels.

NSE Adaptation of Fabio's "big trades" / "protection levels" concept.
Since NSE doesn't provide tick-by-tick order flow, we use OI as a proxy:

  CALL WALL: High OI at call strike = resistance (call writers defending)
  PUT WALL:  High OI at put strike = support (put writers defending)

These act as Fabio's "absorption" levels for stop placement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class OIWall:
    """Open Interest wall at a strike price."""

    strike: int
    wall_type: str  # "CALL_WALL" or "PUT_WALL"
    oi: int
    oi_change: int  # change since last interval
    strength: float  # oi / avg_oi ratio (threshold > 3.0 for strong wall)
    confidence: float  # 0.0 to 1.0 based on volume confirmation


class OIWallEngine:
    """Detects OI walls from option chain data.

    Fabio's "protection level" concept adapted for NSE:
    - High OI at strike = visible order book (absorption level)
    - OI change direction confirms conviction
    - Use for stop placement behind these levels
    """

    # Strength threshold for strong walls
    DEFAULT_STRENGTH_THRESHOLD = 2.5  # Lowered for more sensitive detection

    # Minimum OI for consideration (NSE typical values)
    MIN_OI_NIFTY = 50_000
    MIN_OI_BANKNIFTY = 25_000

    def __init__(self, strength_threshold: float = None):
        self._strength_threshold = strength_threshold if strength_threshold is not None else self.DEFAULT_STRENGTH_THRESHOLD

    def detect_walls(
        self,
        option_chain: list[dict],
        underlying: str = "NIFTY",
        spot_price: float = 0.0,
    ) -> list[OIWall]:
        """Detect OI walls from option chain.

        Args:
            option_chain: List of dicts with keys: strike, ce_oi, pe_oi,
                         ce_oi_change, pe_oi_change, ce_volume, pe_volume
            underlying: "NIFTY" or "BANKNIFTY"
            spot_price: Current underlying price for proximity filtering

        Returns:
            List of OIWall objects sorted by strike proximity to spot
        """
        if not option_chain:
            return []

        min_oi = self.MIN_OI_BANKNIFTY if underlying == "BANKNIFTY" else self.MIN_OI_NIFTY

        # Calculate average OI for strength calculation
        ce_ois = [o.get("ce_oi", 0) for o in option_chain if o.get("ce_oi", 0) > 0]
        pe_ois = [o.get("pe_oi", 0) for o in option_chain if o.get("pe_oi", 0) > 0]

        avg_ce_oi = sum(ce_ois) / len(ce_ois) if ce_ois else 1
        avg_pe_oi = sum(pe_ois) / len(pe_ois) if pe_ois else 1

        walls = []

        for option in option_chain:
            strike = option.get("strike", 0)

            # Call wall detection
            ce_oi = option.get("ce_oi", 0)
            ce_oi_change = option.get("ce_oi_change", 0)
            ce_volume = option.get("ce_volume", 0)

            if ce_oi >= min_oi:
                ce_strength = ce_oi / avg_ce_oi if avg_ce_oi > 0 else 1.0
                if ce_strength >= self._strength_threshold:
                    confidence = self._calculate_confidence(
                        ce_oi_change, ce_volume, ce_oi
                    )
                    walls.append(OIWall(
                        strike=strike,
                        wall_type="CALL_WALL",
                        oi=ce_oi,
                        oi_change=ce_oi_change,
                        strength=ce_strength,
                        confidence=confidence,
                    ))

            # Put wall detection
            pe_oi = option.get("pe_oi", 0)
            pe_oi_change = option.get("pe_oi_change", 0)
            pe_volume = option.get("pe_volume", 0)

            if pe_oi >= min_oi:
                pe_strength = pe_oi / avg_pe_oi if avg_pe_oi > 0 else 1.0
                if pe_strength >= self._strength_threshold:
                    confidence = self._calculate_confidence(
                        pe_oi_change, pe_volume, pe_oi
                    )
                    walls.append(OIWall(
                        strike=strike,
                        wall_type="PUT_WALL",
                        oi=pe_oi,
                        oi_change=pe_oi_change,
                        strength=pe_strength,
                        confidence=confidence,
                    ))

        # Sort by proximity to spot price
        if spot_price > 0:
            walls.sort(key=lambda w: abs(w.strike - spot_price))
        else:
            walls.sort(key=lambda w: w.strike)

        return walls

    def _calculate_confidence(
        self, oi_change: int, volume: int, total_oi: int
    ) -> float:
        """Calculate confidence score for wall based on OI change and volume."""
        score = 0.5  # Base confidence

        # OI change confirms conviction
        if abs(oi_change) > total_oi * 0.1:  # 10%+ change
            score += 0.2

        # Volume confirms activity
        if volume > 10_000:
            score += 0.3

        return min(1.0, score)

    def get_nearest_wall(
        self, walls: list[OIWall], price: float, direction: str = "LONG"
    ) -> Optional[OIWall]:
        """Get nearest wall for stop placement.

        For LONG: find nearest PUT_WALL below price for stop
        For SHORT: find nearest CALL_WALL above price for stop
        """
        if not walls:
            return None

        if direction == "LONG":
            put_walls = [w for w in walls if w.wall_type == "PUT_WALL" and w.strike < price]
            return max(put_walls, key=lambda w: w.strike) if put_walls else None
        else:
            call_walls = [w for w in walls if w.wall_type == "CALL_WALL" and w.strike > price]
            return min(call_walls, key=lambda w: w.strike) if call_walls else None

    def align_with_vp_levels(
        self, walls: list[OIWall], val: float, vah: float, poc: float, tolerance: float = 50
    ) -> list[OIWall]:
        """Filter walls that align with volume profile levels.

        When OI wall aligns with VAL/VAH/POC, confidence increases.
        This is NSE's equivalent of Fabio's "protection level" + "value area" alignment.
        """
        aligned = []
        for wall in walls:
            # Check alignment with VP levels
            near_val = abs(wall.strike - val) <= tolerance
            near_vah = abs(wall.strike - vah) <= tolerance
            near_poc = abs(wall.strike - poc) <= tolerance

            if near_val or near_vah or near_poc:
                aligned.append(wall)

        return aligned