"""
Unit tests for drive tracker.
"""

import pytest
from datetime import datetime
from src.strategy.drive_tracker import DriveTracker
from src.core.candle_builder import Candle


class TestDriveTracker:
    """Test drive detection logic."""

    def test_first_drive(self):
        """Test first drive is detected."""
        tracker = DriveTracker()
        candle = Candle(
            open=9.0, high=9.2, low=8.9, close=9.1,
            volume=100, buy_vol=60, sell_vol=40, delta=20,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        result = tracker.classify_drive(9.1, 9.0, candle, "LONG")
        assert result.drive_number == 1
        assert result.entry_valid == False

    def test_second_drive_valid(self):
        """Test second drive with rejection is valid."""
        tracker = DriveTracker()
        candle1 = Candle(
            open=9.0, high=9.2, low=8.9, close=9.1,
            volume=100, buy_vol=60, sell_vol=40, delta=20,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        tracker.classify_drive(9.1, 9.0, candle1, "LONG")

        # Second drive with rejection (wick through 9.0, close above 9.0)
        candle2 = Candle(
            open=9.1, high=9.2, low=8.8, close=9.05,  # Wick through, close above
            volume=80, buy_vol=40, sell_vol=40, delta=0,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        result = tracker.classify_drive(9.0, 9.0, candle2, "LONG")
        assert result.drive_number == 2
        assert result.entry_valid == True

    def test_third_drive_suppressed(self):
        """Test third drive is suppressed."""
        tracker = DriveTracker()
        candle = Candle(
            open=9.0, high=9.2, low=8.9, close=9.1,
            volume=100, buy_vol=60, sell_vol=40, delta=20,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        tracker.classify_drive(9.1, 9.0, candle, "LONG")
        tracker.classify_drive(9.1, 9.0, candle, "LONG")
        result = tracker.classify_drive(9.1, 9.0, candle, "LONG")
        assert result.drive_number == 3
        assert result.entry_valid == False

    def test_rejection_detection(self):
        """Test rejection detection."""
        candle = Candle(
            open=9.1, high=9.2, low=8.8, close=9.05,  # Wick through 9.0, close above
            volume=100, buy_vol=60, sell_vol=40, delta=20,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        rejected = DriveTracker.detect_rejection(candle, 9.0, "LONG")
        assert rejected == True

    def test_momentum_fade(self):
        """Test momentum fade detection."""
        faded = DriveTracker.check_momentum_fade(80, 100)  # 80% of first
        assert faded == True