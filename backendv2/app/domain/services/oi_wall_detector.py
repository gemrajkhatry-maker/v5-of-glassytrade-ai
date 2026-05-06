"""OI wall detection helper for NSE-style protection levels."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OIWall:
    """Represents an OI wall at one strike."""

    strike: float
    option_type: str
    oi: int
    volume: int
    price_level: str
    strength: float


@dataclass
class OIWallAnalysis:
    call_walls: list[OIWall]
    put_walls: list[OIWall]
    avg_ce_oi: float
    avg_pe_oi: float
    max_ce_wall: OIWall | None = None
    max_pe_wall: OIWall | None = None


def detect_oi_walls(option_chain, threshold: float = 3.0) -> OIWallAnalysis:
    calls = getattr(option_chain, "calls", {})
    puts = getattr(option_chain, "puts", {})

    ce_oi_values = [opt.oi for opt in calls.values() if getattr(opt, "oi", 0) > 0]
    pe_oi_values = [opt.oi for opt in puts.values() if getattr(opt, "oi", 0) > 0]

    avg_ce_oi = sum(ce_oi_values) / len(ce_oi_values) if ce_oi_values else 0.0
    avg_pe_oi = sum(pe_oi_values) / len(pe_oi_values) if pe_oi_values else 0.0

    call_walls: list[OIWall] = []
    put_walls: list[OIWall] = []

    for strike, opt in calls.items():
        oi = int(getattr(opt, "oi", 0))
        if oi > 0 and avg_ce_oi > 0 and oi > threshold * avg_ce_oi:
            call_walls.append(
                OIWall(
                    strike=float(strike),
                    option_type="CE",
                    oi=oi,
                    volume=int(getattr(opt, "volume", 0)),
                    price_level="resistance",
                    strength=oi / avg_ce_oi,
                )
            )

    for strike, opt in puts.items():
        oi = int(getattr(opt, "oi", 0))
        if oi > 0 and avg_pe_oi > 0 and oi > threshold * avg_pe_oi:
            put_walls.append(
                OIWall(
                    strike=float(strike),
                    option_type="PE",
                    oi=oi,
                    volume=int(getattr(opt, "volume", 0)),
                    price_level="support",
                    strength=oi / avg_pe_oi,
                )
            )

    max_ce_wall = max(call_walls, key=lambda wall: wall.oi) if call_walls else None
    max_pe_wall = max(put_walls, key=lambda wall: wall.oi) if put_walls else None

    return OIWallAnalysis(
        call_walls=call_walls,
        put_walls=put_walls,
        avg_ce_oi=avg_ce_oi,
        avg_pe_oi=avg_pe_oi,
        max_ce_wall=max_ce_wall,
        max_pe_wall=max_pe_wall,
    )


def get_key_levels(option_chain, threshold: float = 3.0) -> dict[str, float | None]:
    analysis = detect_oi_walls(option_chain, threshold)
    return {
        "resistance": analysis.max_ce_wall.strike if analysis.max_ce_wall else None,
        "support": analysis.max_pe_wall.strike if analysis.max_pe_wall else None,
    }


def is_oi_wall_near_price(option_chain, target_strike: float, max_distance: int = 100) -> bool:
    analysis = detect_oi_walls(option_chain)
    for wall in analysis.call_walls + analysis.put_walls:
        if abs(wall.strike - target_strike) <= max_distance:
            return True
    return False

