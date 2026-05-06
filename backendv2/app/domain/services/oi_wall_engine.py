"""OI wall engine for protection-level inference."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OIWall:
    strike: int
    wall_type: str
    oi: int
    oi_change: int
    strength: float
    confidence: float


class OIWallEngine:
    """Derive likely support/resistance walls from option chain OI."""

    DEFAULT_STRENGTH_THRESHOLD = 2.5
    MIN_OI_NIFTY = 50_000
    MIN_OI_BANKNIFTY = 25_000

    def __init__(self, strength_threshold: float | None = None) -> None:
        self._strength_threshold = (
            strength_threshold
            if strength_threshold is not None
            else self.DEFAULT_STRENGTH_THRESHOLD
        )

    def detect_walls(
        self,
        option_chain: list[dict],
        underlying: str = "NIFTY",
        spot_price: float = 0.0,
    ) -> list[OIWall]:
        if not option_chain:
            return []

        min_oi = self.MIN_OI_BANKNIFTY if underlying == "BANKNIFTY" else self.MIN_OI_NIFTY
        ce_ois = [o.get("ce_oi", 0) for o in option_chain if o.get("ce_oi", 0) > 0]
        pe_ois = [o.get("pe_oi", 0) for o in option_chain if o.get("pe_oi", 0) > 0]
        avg_ce_oi = sum(ce_ois) / len(ce_ois) if ce_ois else 1
        avg_pe_oi = sum(pe_ois) / len(pe_ois) if pe_ois else 1

        walls: list[OIWall] = []

        for option in option_chain:
            strike = int(option.get("strike", 0))

            ce_oi = int(option.get("ce_oi", 0))
            ce_oi_change = int(option.get("ce_oi_change", 0))
            ce_volume = int(option.get("ce_volume", 0))
            if ce_oi >= min_oi:
                ce_strength = ce_oi / avg_ce_oi if avg_ce_oi > 0 else 1.0
                if ce_strength >= self._strength_threshold:
                    confidence = self._calculate_confidence(ce_oi_change, ce_volume, ce_oi)
                    walls.append(OIWall(strike, "CALL_WALL", ce_oi, ce_oi_change, ce_strength, confidence))

            pe_oi = int(option.get("pe_oi", 0))
            pe_oi_change = int(option.get("pe_oi_change", 0))
            pe_volume = int(option.get("pe_volume", 0))
            if pe_oi >= min_oi:
                pe_strength = pe_oi / avg_pe_oi if avg_pe_oi > 0 else 1.0
                if pe_strength >= self._strength_threshold:
                    confidence = self._calculate_confidence(pe_oi_change, pe_volume, pe_oi)
                    walls.append(OIWall(strike, "PUT_WALL", pe_oi, pe_oi_change, pe_strength, confidence))

        if spot_price > 0:
            walls.sort(key=lambda w: abs(w.strike - spot_price))
        else:
            walls.sort(key=lambda w: w.strike)
        return walls

    def _calculate_confidence(self, oi_change: int, volume: int, total_oi: int) -> float:
        score = 0.5
        if abs(oi_change) > total_oi * 0.1:
            score += 0.2
        if volume > 10_000:
            score += 0.3
        return min(1.0, score)

    def get_nearest_wall(self, walls: list[OIWall], price: float, direction: str = "LONG") -> OIWall | None:
        if not walls:
            return None
        if direction == "LONG":
            put_walls = [w for w in walls if w.wall_type == "PUT_WALL" and w.strike < price]
            return max(put_walls, key=lambda w: w.strike) if put_walls else None
        call_walls = [w for w in walls if w.wall_type == "CALL_WALL" and w.strike > price]
        return min(call_walls, key=lambda w: w.strike) if call_walls else None

    def align_with_vp_levels(self, walls: list[OIWall], val: float, vah: float, poc: float, tolerance: float = 50) -> list[OIWall]:
        aligned: list[OIWall] = []
        for wall in walls:
            near_val = abs(wall.strike - val) <= tolerance
            near_vah = abs(wall.strike - vah) <= tolerance
            near_poc = abs(wall.strike - poc) <= tolerance
            if near_val or near_vah or near_poc:
                aligned.append(wall)
        return aligned

