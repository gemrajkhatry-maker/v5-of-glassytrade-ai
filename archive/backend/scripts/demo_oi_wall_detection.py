"""
Demo: Using OI Wall Detection with Dhan Broker Option Chain.

This shows how to:
1. Fetch option chain from Dhan broker
2. Detect OI walls (support/resistance levels)
3. Use walls for trade decisions
"""

import asyncio
from datetime import datetime

# Mock Dhan broker for demo (would use real client in production)
from shared.entities.models import Option, OptionChain, Instrument, Exchange
from backend.app.domain.services.oi_wall_detector import detect_oi_walls, get_key_levels


def create_demo_option_chain():
    """Create demo option chain showing typical NIFTY OI walls."""
    underlying = Instrument(symbol="NIFTY", exchange=Exchange.NSE)
    expiry = datetime(2026, 5, 29)
    
    calls = {}
    puts = {}
    
    # Simulate real NIFTY option chain with typical OI walls
    # Spot around 24500, with major call wall at 24800 and put wall at 24200
    
    strikes = [24000, 24100, 24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900, 25000]
    
    # Call OI - high at 24800 (call wall = resistance)
    for strike in strikes:
        # 24800 needs > 3x average (which is ~200k), so 700k+
        oi = 800000 if strike == 24800 else 200000
        calls[strike] = Option(
            symbol=f"NIFTY {strike} CE",
            security_id=f"ce_{strike}",
            strike=strike,
            option_type="CE",
            expiry=expiry,
            ltp=50.0 + (strike - 24500) * 0.1,
            oi=oi,
            volume=50000 if strike == 24800 else 20000
        )
    
    # Put OI - high at 24200 (put wall = support)
    for strike in strikes:
        # 24200 needs > 3x average (which is ~150k), so 600k+
        oi = 800000 if strike == 24200 else 150000
        puts[strike] = Option(
            symbol=f"NIFTY {strike} PE",
            security_id=f"pe_{strike}",
            strike=strike,
            option_type="PE",
            expiry=expiry,
            ltp=50.0 - (strike - 24500) * 0.1,
            oi=oi,
            volume=60000 if strike == 24200 else 15000
        )
    
    return OptionChain(
        underlying=underlying,
        expiry=expiry,
        spot_price=24530.0,
        atm_strike=24500,
        step_size=100.0,
        calls=calls,
        puts=puts
    )


def demo_oi_wall_detection():
    """Demo OI wall detection."""
    print("=" * 60)
    print("OI WALL DETECTION DEMO FOR NIFTY OPTIONS")
    print("=" * 60)
    
    # Get option chain (from broker in production)
    chain = create_demo_option_chain()
    
    print(f"\nSpot Price: ₹{chain.spot_price}")
    print(f"ATM Strike: {chain.atm_strike}")
    
    # Detect walls
    analysis = detect_oi_walls(chain)
    
    print(f"\n--- CALL WALLS (Resistance) ---")
    if analysis.call_walls:
        for wall in analysis.call_walls:
            print(f"  Strike {wall.strike}: {wall.oi:,} OI ({wall.strength:.1f}x avg) - RESISTANCE")
    else:
        print("  No call walls detected")
    
    print(f"\n--- PUT WALLS (Support) ---")
    if analysis.put_walls:
        for wall in analysis.put_walls:
            print(f"  Strike {wall.strike}: {wall.oi:,} OI ({wall.strength:.1f}x avg) - SUPPORT")
    else:
        print("  No put walls detected")
    
    # Key levels
    levels = get_key_levels(chain)
    print(f"\n--- KEY LEVELS FOR TRADE ---")
    print(f"  Resistance: {levels['resistance']} (call wall)")
    print(f"  Support: {levels['support']} (put wall)")
    
    # Trade decision example
    print(f"\n--- TRADE DECISION ---")
    print("For LONG trades:")
    print(f"  - Stop below support at {levels['support'] - 100 if levels['support'] else 'N/A'}")
    print("For SHORT trades:")
    if levels['resistance']:
        print(f"  - Stop above resistance at {levels['resistance'] + 100}")
    else:
        print("  - No resistance level identified")


if __name__ == "__main__":
    demo_oi_wall_detection()