"""Unit tests for OrderFlow Detectors — BigTrade, Bubble, OFI, Absorption per FR-03."""

import pytest
from app.domain.fabio_ai.services.orderflow_detectors import (
    BigTradeDetector,
    BubbleDetector,
    OFICalculator,
    AbsorptionDetector,
    BigTradeCluster,
    BubbleResult,
    OFIResult,
    AbsorptionResult,
)
from app.domain.trading.models.value_objects import OHLC


def _candle(close=100, volume=500, delta=100, high=None, low=None, time="t"):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time=time, open=close, high=h, low=l, close=close,
                volume=volume, vwap=0, delta=delta)


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


class TestAbsorptionDetector:
    """FR-03-09/10: Absorption candle detection."""

    def test_detects_absorption(self):
        """Small range + high volume → absorption detected."""
        detector = AbsorptionDetector()
        # range=0.28, ATR=1.0 → 0.28 < 0.30 ✓
        # volume=500, avg=200 → 2.5 > 2.0 ✓
        candle = _candle(close=100, high=100.14, low=99.86, volume=500, delta=100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.detected is True

    def test_no_absorption_wide_range(self):
        """Wide range → no absorption."""
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=101.0, low=99.0, volume=500, delta=100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.detected is False

    def test_no_absorption_low_volume(self):
        """Low volume → no absorption."""
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=100.15, low=99.85, volume=200, delta=100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.detected is False

    def test_classifies_sell_absorbed(self):
        """Positive delta → SELL_ABSORBED (bullish)."""
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=100.14, low=99.86, volume=500, delta=100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.side == "SELL_ABSORBED"

    def test_classifies_buy_absorbed(self):
        """Negative delta → BUY_ABSORBED (bearish)."""
        detector = AbsorptionDetector()
        candle = _candle(close=100, high=100.14, low=99.86, volume=500, delta=-100)
        result = detector.detect(candle, atr=1.0, avg_vol=200)
        assert result.side == "BUY_ABSORBED"
