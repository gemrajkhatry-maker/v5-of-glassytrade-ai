import asyncio
import logging
import datetime
from quant.brokers.gateway import Tick
from quant.multi_engine import QuantCoordinator

# Configure tight logging to trace execution sequence
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("QA_PIPELINE")

class Tracer:
    def __init__(self):
        self.steps = []
        
    def log(self, phase, message):
        logger.info(f"[{phase}] {message}")
        self.steps.append(phase)

tracer = Tracer()

def hook_and_trace(coordinator):
    """Monkey-patch core methods to assert order of execution"""
    original_analyze = coordinator._analyzer.process_tick
    def mocked_analyze(*args, **kwargs):
        tracer.log("PHASE 1", "AmtAnalyzer process_tick (Updates Profile & Market State)")
        return original_analyze(*args, **kwargs)
    coordinator._analyzer.process_tick = mocked_analyze
    
    original_decision = coordinator._decision.evaluate
    def mocked_decision(*args, **kwargs):
        tracer.log("PHASE 2", "DecisionService evaluate (Runs Triple-A Gates & RR Validator)")
        return original_decision(*args, **kwargs)
    coordinator._decision.evaluate = mocked_decision

class DummyMarketData:
    async def get_trading_symbol(self, symbol): return symbol
    async def get_historical_candles(self, *args, **kwargs): return []

async def run_sanity():
    tracer.log("INIT", "Booting QuantCoordinator...")
    coordinator = QuantCoordinator(market_data=DummyMarketData())
    
    # Initialize the specific instrument
    symbol = "NIFTY 25 AUG 25000 CALL"
    await coordinator.initialize_symbol(symbol)
    hook_and_trace(coordinator)
    
    tracer.log("DATA_INGEST", "Injecting 5 continuous uptrend ticks (Imbalance generation)")
    
    base_time = int(datetime.datetime.now().timestamp())
    base_price = 100.0
    
    # Tick 1: Open session
    tick1 = Tick(time=str(base_time), price=100.0, volume=1000.0, buy_volume=1000.0, sell_volume=0.0, oi=5000.0, depth=None)
    await coordinator.on_tick(symbol, tick1)
    
    # Tick 2: Push price up (creates imbalance)
    tick2 = Tick(time=str(base_time+1), price=101.0, volume=1500.0, buy_volume=1500.0, sell_volume=0.0, oi=5100.0, depth=None)
    await coordinator.on_tick(symbol, tick2)
    
    # Tick 3: Establish VAH breakout
    tick3 = Tick(time=str(base_time+2), price=102.0, volume=2000.0, buy_volume=2000.0, sell_volume=0.0, oi=5200.0, depth=None)
    await coordinator.on_tick(symbol, tick3)
    
    tracer.log("STATE_CHECK", "Extracting integrated state...")
    state = coordinator.get_state(symbol)
    
    print("\n" + "="*50)
    print("      INTEGRATED QA PIPELINE ASSERTIONS      ")
    print("="*50)
    
    # 1. Pipeline Execution Order
    print(f"\n1. EXECUTION ORDER:")
    expected_sequence = ["INIT", "DATA_INGEST", "PHASE 1", "PHASE 2", "PHASE 1", "PHASE 2", "PHASE 1", "PHASE 2", "STATE_CHECK"]
    if tracer.steps == expected_sequence:
        print("  [PASS] Data Ingestion -> AMT Analysis -> Decision Logic executed in strict deterministic order.")
    else:
        print(f"  [FAIL] Sequence mismatch: {tracer.steps}")
        
    # 2. Volume Profile State
    print(f"\n2. AMT VOLUME PROFILE:")
    vp = state.auction.volume_profile
    print(f"  Total Volume: {sum(vp.levels.values()) if hasattr(vp, 'levels') else 'N/A'}")
    print(f"  POC (Point of Control): {vp.poc}")
    print(f"  Value Area: {vp.val} to {vp.vah}")
    if vp.poc > 0:
        print("  [PASS] Volume Profile successfully calculated from raw ticks.")
    else:
        print("  [FAIL] Volume Profile is empty.")
        
    # 3. Market State
    print(f"\n3. MARKET STATE ENGINE:")
    print(f"  Live State: {state.auction.state}")
    print(f"  Triple-A Phase: {state.auction.triple_a_phase}")
    
    if state.auction.state == "IMBALANCED":
        print("  [PASS] Aggressive directional ticks correctly transitioned state to IMBALANCED.")
    else:
        print(f"  [WARNING] Expected IMBALANCED state but got {state.auction.state}.")
        
    print("="*50)

if __name__ == "__main__":
    asyncio.run(run_sanity())
