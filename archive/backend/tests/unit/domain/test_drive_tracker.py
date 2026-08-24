"""Unit tests for DriveTracker — D1/D2/D3+ drive detection per Fabio FR-05."""

import pytest
from quant.amt.orderflow.drive import DriveTracker
from quant.contracts.value_objects import OHLC


def _candle(close=100, high=None, low=None, volume=500, time="t"):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time=time, open=close, high=h, low=l, close=close,
                volume=volume, vwap=0, delta=100)


class TestDriveTrackerBasic:
    """FR-05: Drive tracking at key levels."""

    def test_first_touch_is_d1(self):
        """First touch of level → D1, entry_valid=False."""
        tracker = DriveTracker()
        candle = _candle(close=100.2, high=100.5, low=99.5)
        result = tracker.classify_touch(
            price=100.0, level=100.0, candle=candle, direction="LONG",
        )
        assert result.drive_number == 1
        assert result.entry_valid is False

    def test_d1_rejection_detected(self):
        """D1 with rejection (wick through, close opposite) → marked as rejected."""
        tracker = DriveTracker()
        # Wick below level (99.0 < 100.0), close above (100.3 > 100.0)
        candle = _candle(close=100.3, high=100.5, low=99.0)
        result = tracker.classify_touch(
            price=100.0, level=100.0, candle=candle, direction="LONG",
        )
        assert result.rejection_detected is True

    def test_d2_after_rejection(self):
        """D2 after D1 rejected → entry_valid=True."""
        tracker = DriveTracker()
        # D1 with rejection
        candle1 = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle1, direction="LONG")
        # D2 re-touch
        candle2 = _candle(close=100.1, high=100.3, low=99.5)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle2, direction="LONG")
        assert result.drive_number == 2
        assert result.entry_valid is True

    def test_d2_without_rejection(self):
        """D2 without D1 rejection → entry_valid=False."""
        tracker = DriveTracker()
        # D1 without rejection (close below level = same side as SHORT test from below)
        candle1 = _candle(close=99.9, high=100.5, low=99.8)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle1, direction="LONG")
        # D2 re-touch
        candle2 = _candle(close=100.1, high=100.3, low=99.5)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle2, direction="LONG")
        assert result.drive_number == 2
        assert result.entry_valid is False

    def test_d3_suppression(self):
        """D3+ → entry_valid=False (level exhausted)."""
        tracker = DriveTracker()
        # D1 with rejection
        candle1 = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle1, direction="LONG")
        # D2
        candle2 = _candle(close=100.1, high=100.3, low=99.5)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle2, direction="LONG")
        # D3
        candle3 = _candle(close=100.0, high=100.2, low=99.8)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle3, direction="LONG")
        assert result.drive_number >= 3
        assert result.entry_valid is False


class TestDriveTrackerRejection:
    """FR-05-03: Rejection detection."""

    def test_long_rejection(self):
        """LONG rejection: wick below level, close above."""
        tracker = DriveTracker()
        candle = _candle(close=100.3, high=100.5, low=99.0)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="LONG")
        assert result.rejection_detected is True

    def test_short_rejection(self):
        """SHORT rejection: wick above level, close below."""
        tracker = DriveTracker()
        candle = _candle(close=99.7, high=101.0, low=99.5)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="SHORT")
        assert result.rejection_detected is True

    def test_no_rejection_same_side(self):
        """No rejection when close on same side as entry."""
        tracker = DriveTracker()
        candle = _candle(close=99.9, high=100.5, low=99.8)
        result = tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="LONG")
        assert result.rejection_detected is False


class TestDriveTrackerSessionReset:
    """FR-05-08: Session reset."""

    def test_reset_clears_history(self):
        """Session reset clears all level history."""
        tracker = DriveTracker()
        candle = _candle(close=100.3, high=100.5, low=99.0)
        tracker.classify_touch(price=100.0, level=100.0, candle=candle, direction="LONG")
        assert len(tracker._levels) > 0
        tracker.reset()
        assert len(tracker._levels) == 0
