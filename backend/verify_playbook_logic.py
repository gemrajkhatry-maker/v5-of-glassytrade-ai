import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Add backend to path
sys.path.append("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")

# Mock mlx compute before importing modules that use it
import sys
sys.modules['app.domain.fabio_ai.services.mlx_compute'] = MagicMock()
mock_mc = sys.modules['app.domain.fabio_ai.services.mlx_compute']
mock_mc.smooth_array = lambda data, window: data  # simple passthrough
mock_mc.aggression_sigma = lambda vol, hist, period: 1.0 # mock sigma

from app.domain.trading.models.value_objects import OHLC, AMTResult
from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer
from app.domain.fabio_ai.services.entry_gates.three_align import three_align_check
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import check_confirmation_bundle
from app.domain.trading.models.enums import MarketState

def create_candle(close, open_=None, high=None, low=None, volume=1000, delta=100):
    if open_ is None: open_ = close
    if high is None: high = max(open_, close) + 0.5
    if low is None: low = min(open_, close) - 0.5
    return OHLC(
        time=datetime.now(timezone.utc).isoformat(),
        open=open_, high=high, low=low, close=close,
        volume=volume, delta=delta, taker_buy_volume=volume//2
    )

class TestFabioPlaybook(unittest.TestCase):
    def setUp(self):
        self.analyzer = AMTAnalyzer()

    def test_displacement_detection(self):
        print("\n--- Test Displacement ---")
        # Case 1: 3 bullish candles with range expansion
        data = []
        # Pre-context (small range)
        for _ in range(20):
            data.append(create_candle(100, 100, 100.2, 99.8))
        
        # Impulse leg (Strong closes - tight wicks)
        data.append(create_candle(101, 100, 101.1, 99.9))
        data.append(create_candle(102, 101, 102.1, 100.9))
        data.append(create_candle(103, 102, 103.1, 101.9))
        
        result = self.analyzer.detect_displacement(data)
        print(f"Displacement Detected: {result}")
        self.assertTrue(result, "Should detect bullish displacement")

    def test_acceptance_detection(self):
        print("\n--- Test Acceptance ---")
        data = []
        data.append(create_candle(105)) # Outside
        data.append(create_candle(105)) # Outside
        
        result = self.analyzer.detect_acceptance(data, vah=104, val=100)
        print(f"Acceptance Detected: {result}")
        self.assertTrue(result, "Should detect acceptance > VAH")

        result_fail = self.analyzer.detect_acceptance(data, vah=106, val=100)
        self.assertFalse(result_fail, "Should fail if inside VAH")

    def test_confirmation_bundle(self):
        print("\n--- Test Confirmation Bundle (2/3 Rule) ---")
        # 20 candles with high variance (50, 150) -> Mean=100, Std=50
        # Tick 160 = +60 from mean = 1.2 sigma (Fail Sigma)
        # Tick 160 > 100*1.5 = 150 (Pass Vol Impulse)
        data = [create_candle(100, volume=50 if i%2==0 else 150) for i in range(20)]
        
        # Scenario 1: Only Vol Impulse (Fail)
        # Vol=160 (>150), Delta=10 (Ratio 0.06 < 0.15)
        tick1 = create_candle(100, volume=160, delta=10) 
        res1 = check_confirmation_bundle(data, tick1)
        print(f"Vol Impulse Only: {res1}")
        self.assertFalse(res1, "Should fail with only 1/3 (Vol Impulse)")

        # Scenario 2: Vol Impulse + Delta Pressure (Pass)
        # Delta=30 (Ratio 30/160 = 0.18 > 0.15)
        tick2 = create_candle(100, volume=160, delta=30)
        res2 = check_confirmation_bundle(data, tick2)
        print(f"Vol + Delta: {res2}")
        self.assertTrue(res2, "Should pass with 2/3 (Vol + Delta)")

    def test_three_align_gate(self):
        print("\n--- Test Three-Align Gate ---")
        data = [create_candle(100, volume=100) for _ in range(50)]
        tick = create_candle(100, volume=200, delta=40) # Confirmation Pass (Vol+Delta)
        
        # Case 1: Market State UNCLEAR -> Fail
        amt_res = AMTResult(
            market_state="UNCLEAR", poc=100, value_area_high=102, value_area_low=98,
            lvns=(100,), hvns=(), aggression=0, signal=None, setup=None, profile=(), aggressive_prints=()
        )
        gate_passed, conf_ok, _ = three_align_check(data, amt_res, tick, return_is_second_drive=True)
        self.assertFalse(gate_passed, "Should fail on Market State")

        # Case 2: Not near level -> Fail
        # Tick at 101.5 avoids round number (100 is a round number)
        tick_far = create_candle(101.5, volume=200, delta=40)
        amt_res_bal = AMTResult(
            market_state="BALANCED", poc=115, value_area_high=118, value_area_low=112, 
            lvns=(115,), hvns=(), aggression=0, signal=None, setup=None, profile=(), aggressive_prints=()
        )
        gate_passed, conf_ok, _ = three_align_check(data, amt_res_bal, tick_far, return_is_second_drive=True)
        self.assertFalse(gate_passed, "Should fail on Location")

        # Case 3: All Good -> Pass
        amt_res_ok = AMTResult(
            market_state="BALANCED", poc=100, value_area_high=102, value_area_low=98, # Tick at 100 = POC
            lvns=(100,), hvns=(), aggression=0, signal=None, setup=None, profile=(), aggressive_prints=()
        )
        gate_passed, conf_ok, _ = three_align_check(data, amt_res_ok, tick, return_is_second_drive=True)
        self.assertTrue(gate_passed, "Should pass when State, Location, Aggression align")
        print(f"Three Align: {gate_passed}")

if __name__ == '__main__':
    unittest.main()
