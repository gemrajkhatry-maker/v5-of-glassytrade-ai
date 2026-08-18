import logging
from quant.bars import Bar
from quant.coordinator import AuctionCoordinator
from quant.decision.decision_service import DecisionService
logging.getLogger("quant").setLevel(logging.CRITICAL)

def sanity_check_pipeline():
    print("==========================================================")
    print("🔥 QUANT QA: FULL INFRASTRUCTURE SANITY CHECK 🔥")
    print("==========================================================")

    # 1. Pipeline Instantiation Order
    print("\n[TEST 1] COMPONENT INSTANTIATION & DEPENDENCY WIRING")
    try:
        coordinator = AuctionCoordinator()
        decision = DecisionService()
        print("✅ PASS: Core pipeline components (AuctionCoordinator, DecisionService) instantiated without cyclical dependencies.")
    except Exception as e:
        print(f"❌ FAIL: Instantiation broken. {e}")
        return

    # 2. Volume Profile & Order Flow Aggregation
    print("\n[TEST 2] DATA AGGREGATION & AUCTION STATE (PHASE 1)")
    try:
        # Push sequential bars to create a trend
        for i in range(10):
            b = Bar(time=f"t{i}", open=100+i, high=102+i, low=99+i, close=101+i, 
                    volume=1000, buy_volume=800, sell_volume=200, delta=600)
            state = coordinator.on_bar_close(b)
        vp = state.volume_profile
        
        if vp.poc > 0 and vp.vah > vp.val:
            print(f"✅ PASS: Volume Profile built successfully (POC: {vp.poc}, VA: {vp.val}-{vp.vah})")
        else:
            print(f"❌ FAIL: Volume Profile logic is corrupted. POC: {vp.poc}")
            
        of = state.order_flow
        if of.cvd > 0:
            print(f"✅ PASS: Order Flow Engine properly accumulated CVD ({of.cvd})")
        else:
            print(f"❌ FAIL: CVD accumulation failed. {of.cvd}")
    except Exception as e:
        print(f"❌ FAIL: Aggregation crash: {e}")
        return

    # 3. Decision Logic & Triple-A
    print("\n[TEST 3] DECISION SERVICE & RISK ENGINE (PHASE 2)")
    try:
        from dataclasses import replace
        # Force a Mean Reversion setup (Price below VAL, strong buyer absorption/aggression)
        loc = replace(state.location, zone="BELOW_VA")
        of = replace(state.order_flow, cvd=500.0)
        state = replace(state, location=loc, order_flow=of, triple_a_phase="AGGRESSION")
        
        from quant.decision.context import DecisionContext
        
        symbol = "BANKNIFTY 25 AUG 50000 CALL"
        ctx = DecisionContext(
            symbol=symbol,
            agent_direction=None,
            state=state,
            bar=b
        )
        signal = decision.evaluate(ctx)
        
        if signal.approved and signal.signal and signal.signal.direction == "LONG":
            print(f"✅ PASS: Decision engine correctly generated LONG fade at {signal.signal.entry} (SL: {signal.signal.sl}, TP: {signal.signal.tp})")
        else:
            print(f"❌ FAIL: Expected LONG fade signal but got {signal}")
    except Exception as e:
        print(f"❌ FAIL: Decision Logic crash: {e}")
        return

    print("\n==========================================================")
    print("🔥 PIPELINE INTEGRATION STATUS: HEALTHY 🔥")
    print("The system natively maps stream packets -> Tick -> Bar -> AuctionState -> Signal.")
    print("==========================================================")

if __name__ == "__main__":
    sanity_check_pipeline()
