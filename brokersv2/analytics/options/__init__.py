"""Options Analytics Infrastructure.

Option chain normalization, Greeks calculations, IV surface, and OI analytics.
"""

from typing import Dict, Any

from brokersv2.analytics.options.events import (
    OptionContract,
    OptionType,
    Moneyness,
    StrikeLevel,
    OptionChainEvent,
    GreeksSnapshot,
    OIEvent,
    IVSurfaceEvent,
)

from brokersv2.analytics.options.greeks import (
    calculate_greeks,
    GreeksResult,
    GreeksCalculator,
)

from brokersv2.analytics.options.volatility_surface import (
    calculate_skew,
    calculate_term_structure,
    IVSurface,
    SkewMetrics,
    TermStructureMetrics,
)

def detect_buildups(
    chain: OptionChainEvent,
    oi_change_threshold: float = 0.10,
    volume_threshold: int = 1000,
) -> Dict[str, Any]:
    """
    Detect option buildup patterns based on OI and volume changes.
    
    Analyzes option chain to identify:
    - Call buildups: Significant OI increase in calls
    - Put buildups: Significant OI increase in puts
    - Call unwinding: Significant OI decrease in calls
    - Put unwinding: Significant OI decrease in puts
    
    Args:
        chain: Option chain event with strikes and contract data
        oi_change_threshold: Minimum OI change percentage to qualify (default 10%)
        volume_threshold: Minimum volume to consider (default 1000)
    
    Returns:
        Dict with categorized buildup patterns and metadata
    """
    from dataclasses import asdict
    
    buildups = {
        "call_buildup": [],
        "put_buildup": [],
        "call_unwinding": [],
        "put_unwinding": [],
        "metadata": {
            "underlying": chain.underlying,
            "timestamp": chain.timestamp.isoformat(),
            "expiry": chain.expiry.isoformat(),
            "atm_strike": chain.atm_strike,
            "threshold_pct": oi_change_threshold * 100,
        }
    }
    
    for strike_level in chain.strikes:
        # Analyze call contracts
        if strike_level.call and strike_level.call_oi > 0:
            call = strike_level.call
            # Calculate implied OI change from volume vs existing OI
            oi_change_ratio = call.volume / max(call.open_interest, 1)
            
            if call.volume >= volume_threshold:
                contract_data = {
                    "strike": strike_level.strike,
                    "symbol": call.symbol,
                    "oi": call.open_interest,
                    "volume": call.volume,
                    "ltp": call.ltp,
                    "iv": call.implied_volatility,
                    "oi_change_ratio": round(oi_change_ratio, 4),
                }
                
                if oi_change_ratio > oi_change_threshold:
                    buildups["call_buildup"].append(contract_data)
                elif oi_change_ratio < -oi_change_threshold:
                    buildups["call_unwinding"].append(contract_data)
        
        # Analyze put contracts
        if strike_level.put and strike_level.put_oi > 0:
            put = strike_level.put
            oi_change_ratio = put.volume / max(put.open_interest, 1)
            
            if put.volume >= volume_threshold:
                contract_data = {
                    "strike": strike_level.strike,
                    "symbol": put.symbol,
                    "oi": put.open_interest,
                    "volume": put.volume,
                    "ltp": put.ltp,
                    "iv": put.implied_volatility,
                    "oi_change_ratio": round(oi_change_ratio, 4),
                }
                
                if oi_change_ratio > oi_change_threshold:
                    buildups["put_buildup"].append(contract_data)
                elif oi_change_ratio < -oi_change_threshold:
                    buildups["put_unwinding"].append(contract_data)
    
    # Sort by OI change ratio (descending for buildups)
    buildups["call_buildup"].sort(key=lambda x: x["oi_change_ratio"], reverse=True)
    buildups["put_buildup"].sort(key=lambda x: x["oi_change_ratio"], reverse=True)
    buildups["call_unwinding"].sort(key=lambda x: x["oi_change_ratio"])
    buildups["put_unwinding"].sort(key=lambda x: x["oi_change_ratio"])
    
    return buildups

__all__ = [
    "OptionContract",
    "OptionType",
    "Moneyness",
    "StrikeLevel",
    "OptionChainEvent",
    "GreeksSnapshot",
    "OIEvent",
    "IVSurfaceEvent",
    "calculate_greeks",
    "GreeksResult",
    "GreeksCalculator",
    "calculate_skew",
    "calculate_term_structure",
    "IVSurface",
    "SkewMetrics",
    "TermStructureMetrics",
    "detect_buildups",
]
