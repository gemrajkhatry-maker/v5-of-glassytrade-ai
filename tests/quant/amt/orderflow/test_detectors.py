"""Unit tests for OrderFlow Detectors — BigTrade, Bubble, OFI, Absorption per FR-03."""

import pytest
from quant.amt.orderflow.detectors import (
    BigTradeDetector,
    BubbleDetector,
    OFICalculator,
    AbsorptionDetector,
    BigTradeCluster,
    BubbleResult,
    OFIResult,
    AbsorptionResult,
)
from quant.contracts.value_objects import OHLC


def _candle(close=100, volume=500, delta=100, high=None, low=None, time="t"):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(
        time=time,
        open=close,
        high=h,
        low=l,
        close=close,
        volume=volume,
        vwap=0,
        delta=delta,
    )


class TestBigTradeDetector:
    """FR-03-11: Institutional big trade cluster detection."""

    def test_detects_high_volume_candle(self):
        """Candle with 5x avg volume → detected."""
        detector = BigTradeDetector(multiplier=5.0)
        candle = _candle(volume=5000)
        result = detector.detect(candle, avg_candle_vol=1000)
        assert result is not None
        assert result.side == "BUY"  # delta > 0

    def test_ignores_normal_volume(self):
        """Candle with normal volume → not detected."""
        detector = BigTradeDetector(multiplier=5.0)
        candle = _candle(volume=1000)
        result = detector.detect(candle, avg_candle_vol=1000)
        assert result is None

    def test_classifies_sell_side(self):
        """Negative delta → SELL side."""
        detector = BigTradeDetector(multiplier=5.0)
        candle = _candle(volume=5000, delta=-300)
        result = detector.detect(candle, avg_candle_vol=1000)
        assert result is not None
        assert result.side == "SELL"


class TestBubbleDetector:
    """FR-03-07/08: Volume bubble detection (2σ threshold)."""

    def test_detects_bubble(self):
        """Candle with volume ≥ mean + 2σ → detected."""
        detector = BubbleDetector(lookback=21)
        # Build history with consistent volume
        for i in range(20):
            detector.detect(_candle(volume=100, time=f"t{i}"))
        # Spike candle
        result = detector.detect(_candle(volume=500, time="t20"))
        assert result.detected is True
        assert result.sigma >= 2.0

    def test_no_bubble_normal_volume(self):
        """Normal volume candle → not detected."""
        detector = BubbleDetector(lookback=21)
        # Use varied volumes so std > 0
        for i in range(20):
            vol = 90 + (i % 5) * 5  # 90, 95, 100, 105, 110
            detector.detect(_candle(volume=vol, time=f"t{i}"))
        # Volume within normal range
        result = detector.detect(_candle(volume=100, time="t20"))
        assert result.detected is False

    def test_classifies_direction(self):
        """Positive delta → BUY direction."""
        detector = BubbleDetector(lookback=21)
        for i in range(20):
            detector.detect(_candle(volume=100, time=f"t{i}"))
        result = detector.detect(_candle(volume=500, delta=200, time="t20"))
        assert result.direction == "BUY"

    def test_classifies_sell_direction(self):
        """Negative delta → SELL direction."""
        detector = BubbleDetector(lookback=21)
        for i in range(20):
            detector.detect(_candle(volume=100, time=f"t{i}"))
        result = detector.detect(_candle(volume=500, delta=-200, time="t20"))
        assert result.direction == "SELL"


class TestOFICalculator:
    """FR-03-12: Order Flow Imbalance over rolling window."""

    def test_positive_ofi(self):
        """More buy volume → positive OFI."""
        calc = OFICalculator(window=10)
        for i in range(10):
            result = calc.update(_candle(volume=100, delta=50, time=f"t{i}"))
        assert result.ofi > 0

    def test_negative_ofi(self):
        """More sell volume → negative OFI."""
        calc = OFICalculator(window=10)
        for i in range(10):
            result = calc.update(_candle(volume=100, delta=-50, time=f"t{i}"))
        assert result.ofi < 0

    def test_zero_ofi(self):
        """Equal buy/sell → OFI ≈ 0."""
        calc = OFICalculator(window=10)
        for i in range(10):
            delta = 50 if i % 2 == 0 else -50
            result = calc.update(_candle(volume=100, delta=delta, time=f"t{i}"))
        assert abs(result.ofi) < 0.1

    def test_ofi_range(self):
        """OFI always between -1.0 and +1.0."""
        calc = OFICalculator(window=10)
        for i in range(10):
            result = calc.update(_candle(volume=100, delta=100, time=f"t{i}"))
        assert -1.0 <= result.ofi <= 1.0

    def test_ofi_clamps_extreme_delta(self):
        """OFI clamped when delta exceeds volume (Task 2.4)."""
        calc = OFICalculator(window=10)
        # Feed extreme delta values (delta > volume)
        for i in range(10):
            result = calc.update(_candle(volume=100, delta=500, time=f"t{i}"))
        # Should be clamped to +1.0
        assert -1.0 <= result.ofi <= 1.0
        assert result.ofi == 1.0  # All positive extreme deltas

    def test_ofi_varies_with_data(self):
        """OFI produces different values across varying ticks (Task 2.4)."""
        calc = OFICalculator(window=5)
        ofi_values = []
        
        # Feed varying delta patterns
        for i in range(10):
            delta = 50 if i % 3 == 0 else (-30 if i % 3 == 1 else 10)
            result = calc.update(_candle(volume=100, delta=delta, time=f"t{i}"))
            ofi_values.append(result.ofi)
        
        # Should have some variation (not all same value)
        unique_values = set(round(v, 3) for v in ofi_values)
        assert len(unique_values) > 1, f"OFI should vary, got {len(unique_values)} unique values"

    def test_ofi_zero_volume_returns_zero(self):
        """OFI returns 0.0 when volume is zero (Task 2.4)."""
        calc = OFICalculator(window=10)
        result = calc.update(_candle(volume=0, delta=100, time="t0"))
        assert result.ofi == 0.0


class TestAbsorptionDetector:
    """FR-03-09/10: Absorption candle detection with displacement validation."""

    def test_detects_absorption(self):
        """Small range + high volume + displacement → absorption detected."""
        detector = AbsorptionDetector()
        # First candle: absorption signature (range=0.28 < ATR*0.30, vol=500 > avg*2.0, delta=-100 = sellers absorbed by passive buyers)
        candle1 = _candle(close=100, high=100.14, low=99.86, volume=500, delta=-100)
        result1 = detector.detect(candle1, atr=1.0, avg_vol=200)
        assert result1.detected is False  # pending displacement

        # Second candle: displacement (close beyond absorption high)
        candle2 = _candle(close=100.2, high=100.3, low=100.0, volume=300, delta=50)
        result2 = detector.detect(candle2, atr=1.0, avg_vol=200)
        assert result2.detected is True

    def test_no_absorption_wide_range(self):
        """Wide range → no absorption."""
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=101.0, low=99.0, volume=500, delta=-100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.detected is False

    def test_no_absorption_low_volume(self):
        """Low volume → no absorption."""
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=100.15, low=99.85, volume=200, delta=-100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.detected is False

    def test_classifies_sell_absorbed(self):
        """Negative delta (sellers absorbed) + upward displacement → SELL_ABSORBED (bullish)."""
        detector = AbsorptionDetector()
        candle1 = _candle(close=100, high=100.14, low=99.86, volume=500, delta=-100)
        detector.detect(candle1, atr=1.0, avg_vol=200)
        candle2 = _candle(close=100.2, high=100.3, low=100.0, volume=300, delta=50)
        result = detector.detect(candle2, atr=1.0, avg_vol=200)
        assert result.side == "SELL_ABSORBED"

    def test_classifies_buy_absorbed(self):
        """Positive delta (buyers absorbed) + downward displacement → BUY_ABSORBED (bearish)."""
        detector = AbsorptionDetector()
        candle1 = _candle(close=100, high=100.14, low=99.86, volume=500, delta=100)
        detector.detect(candle1, atr=1.0, avg_vol=200)
        candle2 = _candle(close=99.8, high=100.0, low=99.7, volume=300, delta=-50)
        result = detector.detect(candle2, atr=1.0, avg_vol=200)
        assert result.side == "BUY_ABSORBED"
