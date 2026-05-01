"""
OI Wall Integration with Dhan Broker - Example Usage.

This shows the complete flow:
1. Fetch option chain from Dhan broker
2. Detect OI walls using the OI wall detector
3. Pass wall levels to RiskSizingEngine for trade decisions

Integration point: When entering a trade, detect OI walls and use
the resistance/support levels for stop placement per Fabio's rules:
- For LONG: stop goes below put wall (support)
- For SHORT: stop goes above call wall (resistance)
"""

from datetime import datetime
from typing import Optional

# From Dhan broker
from shared.entities.models import OptionChain, Option
# From backend domain services
from backend.app.domain.services.risk_sizing_engine import RiskSizingEngine, SizingResult
from backend.app.domain.services.oi_wall_detector import get_key_levels, OIWallAnalysis


async def get_trade_sizing_with_oi_walls(
    *,
    equity: float,
    underlying: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    direction: str,
    option_chain: OptionChain,
    broker_options_service,  # Dhan OptionsService instance
    dhan_underlying: str = "NIFTY",
) -> tuple[SizingResult, Optional[OIWallAnalysis]]:
    """
    Complete trade sizing with OI wall integration.
    
    Args:
        equity: Current account equity
        underlying: Trading symbol (NIFTY, BANKNIFTY)
        entry_price: Planned entry price
        stop_price: Initial stop price
        target_price: Target price
        direction: "LONG" or "SHORT"
        option_chain: Option chain from Dhan broker
        broker_options_service: Dhan OptionsService for fetching fresh data
        dhan_underlying: Symbol name for Dhan API
    
    Returns:
        Tuple of (SizingResult, OIWallAnalysis)
    """
    engine = RiskSizingEngine()
    
    # Step 1: Detect OI walls from option chain
    key_levels = get_key_levels(option_chain)
    wall_support = key_levels.get('support')  # Put wall = support
    wall_resistance = key_levels.get('resistance')  # Call wall = resistance
    
    # Get analysis for reference
    analysis = OIWallAnalysis(
        call_walls=[],  # Would need to call detect_oi_walls to populate
        put_walls=[],
        avg_ce_oi=0.0,
        avg_pe_oi=0.0,
    )
    
    # Step 2: Get OI and volume for liquidity filter from ATM strikes
    spot_price = option_chain.spot_price
    calls = option_chain.calls
    puts = option_chain.puts
    
    # Find ATM strike
    all_strikes = sorted(set(calls.keys()) | set(puts.keys()))
    atm_strike = min(all_strikes, key=lambda s: abs(s - spot_price)) if all_strikes else 0.0
    
    # Get OI/volume from ATM option for liquidity check
    oi = 0
    volume = 0
    if atm_strike in calls:
        oi = calls[atm_strike].oi
        volume = calls[atm_strike].volume
    
    # Step 3: Calculate position size with OI wall integration
    result = engine.calculate(
        equity=equity,
        session_pnl=0,
        consecutive_losses=0,
        underlying=underlying,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        direction=direction,
        oi=oi,
        volume=volume,
        oi_wall_support=wall_support,
        oi_wall_resistance=wall_resistance,
    )
    
    # Step 4: Return result with OI analysis info
    if wall_support and direction == "LONG":
        result.reason += f", OI support: {wall_support}"
    if wall_resistance and direction == "SHORT":
        result.reason += f", OI resistance: {wall_resistance}"
    
    return result, analysis


# Example usage in a trading signal handler:
async def example_usage():
    """
    Example showing how to use OI wall integration in a trading flow.
    """
    # 1. Get option chain from broker
    # option_chain = await dhan_options_service.get_option_chain_async("NIFTY", Exchange.NFO)
    
    # 2. For a LONG trade, the stop should be placed below the put wall (support)
    # key_levels = get_key_levels(option_chain)
    # if key_levels['support']:
    #     # Place stop 100 points below support
    #     stop_price = key_levels['support'] - 100
    
    # 3. For a SHORT trade, the stop should be placed above the call wall (resistance)
    # if key_levels['resistance']:
    #     stop_price = key_levels['resistance'] + 100
    
    pass