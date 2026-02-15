import asyncio
import sys
from datetime import datetime, timezone

# Add backend to path
sys.path.append("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")

from app.infrastructure.adapters.binance_adapter import BinanceMarketDataAdapter
from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer, AMTConfig
from app.application.services.trading_session import TradingSessionService, SessionState
from app.domain.trading.models.value_objects import OHLC

async def main():
    print("--- 1. Connecting to Binance ---")
    adapter = BinanceMarketDataAdapter()
    symbol = "BTCUSDT"
    
    print(f"Fetching 500 candles for {symbol}...")
    try:
        data = await adapter.fetch_history(symbol, interval="5m", limit=500)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    if not data:
        print("No data returned.")
        return

    print(f"Received {len(data)} candles. Last close: {data[-1].close}")

    # --- 2. Run AMT Analysis ---
    print("\n--- 2. Running Fabio Playbook Analysis ---")
    analyzer = AMTAnalyzer()
    
    # We strip the last candle to use it as the "live tick" for testing
    history = data[:-1]
    live_tick = data[-1]
    
    result = analyzer.analyze(history)
    
    print("\n[Market State Engine]")
    print(f"  > Value Area: {result.value_area_low:.2f} - {result.value_area_high:.2f} (POC: {result.poc:.2f})")
    print(f"  > Market State: {result.market_state}")
    
    # Manual check of conditions for verification
    has_displacement = analyzer.detect_displacement(history[-20:])
    has_acceptance = analyzer.detect_acceptance(history[-20:], result.value_area_high, result.value_area_low)
    
    print(f"  > Displacement Detected: {has_displacement}")
    print(f"  > Acceptance Detected:   {has_acceptance}")
    print(f"  > (Expected: Imbalanced only if BOTH are True)")

    # --- 3. Run Confirmation Bundle Checks ---
    print("\n[Confirmation Bundle Gate]")
    
    # Mock session for the service method
    session = SessionState(symbol=symbol)
    session.data = history
    
    # We need to access the private methods of TradingSessionService or replicate logic
    # Since we can't easily instantiate the full service with dependencies, we'll verify logic directly matching the service code
    
    def check_confirmation_debug(hist, tick):
        # 1. Volume Impulse
        recent_vols = [d.volume for d in hist[-20:]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1.0
        vol_impulse = tick.volume > (avg_vol * 1.5)
        
        # 2. Delta Pressure
        delta_ratio = abs(tick.delta) / tick.volume if tick.volume > 0 else 0
        delta_pressure = delta_ratio > 0.15
        
        # 3. Aggression Sigma
        from app.domain.fabio_ai.services.amt_analyzer import compute_aggression_sigma
        sigma = compute_aggression_sigma(tick, hist[-50:])
        agg_sigma = sigma >= 2.5
        
        count = sum([vol_impulse, delta_pressure, agg_sigma])
        
        print(f"  > Tick Vol: {tick.volume:.2f} vs Avg: {avg_vol:.2f} (Impulse: {vol_impulse})")
        print(f"  > Delta Ratio: {delta_ratio:.3f} (Threshold 0.15) (Pressure: {delta_pressure})")
        print(f"  > Sigma: {sigma:.2f} (Threshold 2.5) (Aggression: {agg_sigma})")
        print(f"  > Total Confirmation Score: {count}/3 (Pass: {count >= 2})")
        
        return count >= 2

    is_confirmed = check_confirmation_debug(history, live_tick)

    # --- 4. Run Three-Align Gate ---
    print("\n[Three-Align Gate]")
    
    # Location check
    near_level = False
    threshold = live_tick.close * 0.002
    dist_vah = abs(live_tick.close - result.value_area_high)
    dist_val = abs(live_tick.close - result.value_area_low)
    dist_poc = abs(live_tick.close - result.poc)
    
    print(f"  > Distances: VAH={dist_vah:.2f}, VAL={dist_val:.2f}, POC={dist_poc:.2f} (Thresh: {threshold:.2f})")
    
    if dist_vah < threshold or dist_val < threshold or dist_poc < threshold:
        near_level = True
    else:
        # Check LVNs
        for lvn in result.lvns:
            if abs(live_tick.close - lvn) < threshold:
                print(f"  > Near LVN: {lvn:.2f}")
                near_level = True
                break
    
    state_ok = result.market_state in ("BALANCED", "IMBALANCED")
    
    print(f"  > 1. Market State OK: {state_ok} ({result.market_state})")
    print(f"  > 2. Location OK:     {near_level}")
    print(f"  > 3. Confirmation OK: {is_confirmed}")
    
    aligned = state_ok and near_level and is_confirmed
    print(f"  > GATE STATUS: {'OPEN (Trade Allowed)' if aligned else 'CLOSED (Wait)'}")
    print("---------------------------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
