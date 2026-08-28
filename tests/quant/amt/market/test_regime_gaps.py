"""Tests for RegimeDetector squeeze detection (detect_squeeze)."""
from unittest.mock import MagicMock
from quant.amt.market.regime import RegimeDetector


def _ohlc(close, low=None, high=None):
    m = MagicMock()
    m.close = close
    m.low = low if low is not None else close * 0.99
    m.high = high if high is not None else close * 1.01
    m.volume = 1000
    m.delta = 0
    m.time = "2025-01-01T10:00:00Z"
    return m


class TestSqueezeDetection:
    def test_no_squeeze_without_contraction(self):
        rd = RegimeDetector()
        data = [_ohlc(100 + i * 0.5) for i in range(40)]  # trending, not contracting
        amt = MagicMock()
        amt.value_area_low = 95.0
        amt.value_area_high = 105.0
        assert rd.detect_squeeze(data, amt) is None

    def test_no_squeeze_with_insufficient_data(self):
        rd = RegimeDetector()
        data = [_ohlc(100) for _ in range(10)]
        amt = MagicMock()
        amt.value_area_low = 95.0
        amt.value_area_high = 105.0
        assert rd.detect_squeeze(data, amt) is None
