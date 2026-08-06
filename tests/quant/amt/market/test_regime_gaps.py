"""Tests for RegimeDetector second drive and squeeze detection."""
import pytest
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


class TestSecondDrive:
    def test_first_touch_not_second_drive(self):
        rd = RegimeDetector()
        rd.record_level_approach(100.0, [100.0], 1.0)
        assert rd.is_second_drive(100.0, [100.0]) is False

    def test_second_drive_after_retreat(self):
        rd = RegimeDetector()
        # First touch
        rd.record_level_approach(100.0, [100.0], 1.0)
        # Retreat >0.5%
        rd.record_level_approach(100.6, [100.0], 2.0)
        # Second approach
        assert rd.is_second_drive(100.0, [100.0]) is True

    def test_no_second_drive_without_retreat(self):
        rd = RegimeDetector()
        rd.record_level_approach(100.0, [100.0], 1.0)
        rd.record_level_approach(100.2, [100.0], 2.0)  # only 0.2% away
        assert rd.is_second_drive(100.0, [100.0]) is False

    def test_second_drive_with_multiple_levels(self):
        rd = RegimeDetector()
        rd.record_level_approach(100.0, [100.0, 110.0], 1.0)
        rd.record_level_approach(100.6, [100.0, 110.0], 2.0)
        assert rd.is_second_drive(100.0, [100.0, 110.0]) is True
        assert rd.is_second_drive(110.0, [100.0, 110.0]) is False


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

    def test_squeeze_override_unblocks_reentry(self):
        rd = RegimeDetector()
        rd.record_failed_entry(100.0, "LONG", 1)
        # Without squeeze, re-entry blocked
        assert rd.is_re_entry_blocked(100.0, "LONG", 1) is True
        # With squeeze, re-entry allowed
        assert rd.is_re_entry_blocked(100.0, "LONG", 1, squeeze_active=True) is False
