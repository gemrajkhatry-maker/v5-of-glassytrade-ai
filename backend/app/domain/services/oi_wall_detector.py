"""
OI Wall Detection for NSE Options.

Detects call walls (resistance) and put walls (support) from option chain OI data.
Based on Fabio Valentini's AMT strategy - "big trades" / "protection levels".

From amt_docs/fabio_amt_nse_options_rules_and_implementation.md:
- Call Wall: ce_oi > 3 × avg_ce_oi → strong call writing = resistance
- Put Wall: pe_oi > 3 × avg_pe_oi → strong put writing = support
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from shared.entities.models import OptionChain, Option


@dataclass
class OIWall:
    """Represents an OI wall (support or resistance)."""
    strike: float
    option_type: str  # 'CE' or 'PE'
    oi: int
    volume: int
    price_level: str  # 'support' or 'resistance'
    strength: float  # Multiplier of average OI (e.g., 3.5 = 3.5x average)


@dataclass
class OIWallAnalysis:
    """Full OI wall analysis result."""
    call_walls: List[OIWall]
    put_walls: List[OIWall]
    avg_ce_oi: float
    avg_pe_oi: float
    max_ce_wall: Optional[OIWall] = None
    max_pe_wall: Optional[OIWall] = None


def detect_oi_walls(option_chain: OptionChain, threshold: float = 3.0) -> OIWallAnalysis:
    """
    Detect OI walls from option chain.
    
    Args:
        option_chain: Full option chain with OI data
        threshold: Minimum multiple of average OI to qualify as wall (default 3.0)
    
    Returns:
        OIWallAnalysis with all detected walls
    """
    calls = option_chain.calls
    puts = option_chain.puts
    
    # Calculate average OI for calls and puts
    ce_oi_values = [opt.oi for opt in calls.values() if opt.oi > 0]
    pe_oi_values = [opt.oi for opt in puts.values() if opt.oi > 0]
    
    avg_ce_oi = sum(ce_oi_values) / len(ce_oi_values) if ce_oi_values else 0
    avg_pe_oi = sum(pe_oi_values) / len(pe_oi_values) if pe_oi_values else 0
    
    call_walls = []
    put_walls = []
    
    # Detect call walls (resistance)
    for strike, opt in calls.items():
        if opt.oi > 0 and avg_ce_oi > 0 and opt.oi > threshold * avg_ce_oi:
            wall = OIWall(
                strike=strike,
                option_type='CE',
                oi=opt.oi,
                volume=opt.volume,
                price_level='resistance',
                strength=opt.oi / avg_ce_oi
            )
            call_walls.append(wall)
    
    # Detect put walls (support)
    for strike, opt in puts.items():
        if opt.oi > 0 and avg_pe_oi > 0 and opt.oi > threshold * avg_pe_oi:
            wall = OIWall(
                strike=strike,
                option_type='PE',
                oi=opt.oi,
                volume=opt.volume,
                price_level='support',
                strength=opt.oi / avg_pe_oi
            )
            put_walls.append(wall)
    
    # Find strongest walls
    max_ce_wall = max(call_walls, key=lambda w: w.oi) if call_walls else None
    max_pe_wall = max(put_walls, key=lambda w: w.oi) if put_walls else None
    
    return OIWallAnalysis(
        call_walls=call_walls,
        put_walls=put_walls,
        avg_ce_oi=avg_ce_oi,
        avg_pe_oi=avg_pe_oi,
        max_ce_wall=max_ce_wall,
        max_pe_wall=max_pe_wall
    )


def get_key_levels(option_chain: OptionChain, threshold: float = 3.0) -> Dict[str, float]:
    """
    Get key support/resistance levels from OI walls.
    
    Returns dict with:
        - 'resistance': strongest call wall strike (or None)
        - 'support': strongest put wall strike (or None)
    
    These levels align with Fabio's "protection levels":
    - For LONG: stop goes below put wall (support)
    - For SHORT: stop goes above call wall (resistance)
    """
    analysis = detect_oi_walls(option_chain, threshold)
    
    return {
        'resistance': analysis.max_ce_wall.strike if analysis.max_ce_wall else None,
        'support': analysis.max_pe_wall.strike if analysis.max_pe_wall else None
    }


def is_oi_wall_near_price(option_chain: OptionChain, target_strike: float, max_distance: int = 100) -> bool:
    """
    Check if a target strike is near an OI wall.
    
    This helps identify when price is approaching a protection level
    where Fabio would place stops.
    """
    analysis = detect_oi_walls(option_chain)
    
    for wall in analysis.call_walls + analysis.put_walls:
        if abs(wall.strike - target_strike) <= max_distance:
            return True
    
    return False