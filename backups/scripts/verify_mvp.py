import sys
import os
import asyncio

# Add backend to python path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.api.dependencies import get_service_graph

async def verify_mvp():
    print("Initializing Service Graph (Loading AI Model)...")
    try:
        graph = get_service_graph()
        service = graph.gen_ai_service
        print("Model Loaded Successfully!")
        
        # Test Case: AAA Setup
        market_data = {
            "ltp": 15050.0,
            "delta": -500.0,
            "volume": 1200.0,
            "context": "Price is testing Value Area Low (VAL).",
            "aggression": "Sellers are aggressive but absorption is happening",
            "key_level": "VAL"
        }
        
        print(f"\nAnalyzing Market Data: {market_data}")
        result = service.analyze_market(market_data)
        
        print("\n--- MVP Analysis Result ---")
        print(f"Direction: {result['direction']}")
        print(f"Rationale: {result['rationale']}")
        print("---------------------------")
        
        if result['direction'] in ["LONG", "SHORT", "FLAT"]:
            print("\n✅ Service Verification PASSED")
        else:
             print("\n❌ Service Verification FAILED (Invalid Direction)")

        # Test Case 2: Integration via TradingSessionService
        print("\nTesting TradingSessionService Integration...")
        ts_service = graph.trading_session
        
        # Create Dummy Tick
        from app.domain.trading.models.value_objects import OHLC
        tick = OHLC(
            time="2024-01-01T12:00:00Z",
            open=15000.0, high=15100.0, low=14950.0, close=15050.0,
            volume=5000.0, delta=-500.0
        )
        
        print(f"Processing Tick: {tick}")
        state = ts_service.process_tick(symbol="BTCUSD", tick=tick)
        
        print("\n--- Session State AI Analysis ---")
        ai_state = state.get("aiAnalysis")
        if ai_state:
            print(f"Direction: {ai_state['direction']}")
            print(f"Rationale: {ai_state['rationale']}")
            print("\n✅ Integration Verification PASSED")
        else:
            print("\n❌ Integration Verification FAILED (No AI State)")

    except Exception as e:
        print(f"\n❌ Verification FAILED with error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_mvp())
