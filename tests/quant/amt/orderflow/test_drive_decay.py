"""Tests for DriveDecay — ported from backend test_live_trading_safeguards.py."""

import pytest
from datetime import datetime, timedelta, timezone
from quant.amt.orderflow.drive_decay import DriveDecay


IST = timezone(timedelta(hours=5, minutes=30))


class TestDriveDecayRegression:
    """Regression for the record-before-assign UnboundLocalError."""

    def test_validate_drive_2_with_recorded_drive_1(self):
        """validate_drive_2 must not crash on a recorded Drive 1 (Track A3)."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)

        drive1_time = datetime(2026, 3, 20, 9, 30, 0, tzinfo=IST)
        decay.record_drive_1(6100.0, "LONG", drive1_time, tick_size=1.0)

        # Price rotated away by 5 ticks, only 1 minute elapsed
        decay.update_rotation(6095.0)
        drive2_time = datetime(2026, 3, 20, 9, 31, 0, tzinfo=IST)
        result = decay.validate_drive_2(6100.0, 6095.0, drive2_time)

        assert result.valid is True
        assert result.price_decay_met is True


class TestDriveDecay:
    """Test drive time/price decay enforcement."""

    def test_drive_2_valid_after_time_decay(self):
        """Drive 2 should be valid after 3 minutes."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)

        drive1_time = datetime(2026, 3, 20, 9, 30, 0, tzinfo=IST)
        decay.record_drive_1(6100.0, "LONG", drive1_time, tick_size=1.0)

        # 4 minutes later
        drive2_time = datetime(2026, 3, 20, 9, 34, 0, tzinfo=IST)
        result = decay.validate_drive_2(6100.0, 6100.0, drive2_time)
        assert result.valid is True
        assert result.time_decay_met is True

    def test_drive_2_valid_after_price_decay(self):
        """Drive 2 should be valid after price rotation."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)

        drive1_time = datetime(2026, 3, 20, 9, 30, 0, tzinfo=IST)
        decay.record_drive_1(6100.0, "LONG", drive1_time, tick_size=1.0)

        # Price rotated away by 5 ticks
        decay.update_rotation(6095.0)  # 5 ticks away

        # 1 minute later (not enough time)
        drive2_time = datetime(2026, 3, 20, 9, 31, 0, tzinfo=IST)
        result = decay.validate_drive_2(6100.0, 6095.0, drive2_time)
        assert result.valid is True
        assert result.price_decay_met is True

    def test_drive_2_blocked_no_decay(self):
        """Drive 2 should be blocked without time or price decay."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)

        drive1_time = datetime(2026, 3, 20, 9, 30, 0, tzinfo=IST)
        decay.record_drive_1(6100.0, "LONG", drive1_time, tick_size=1.0)

        # No rotation, only 1 minute passed
        drive2_time = datetime(2026, 3, 20, 9, 31, 0, tzinfo=IST)
        result = decay.validate_drive_2(6100.0, 6100.0, drive2_time)
        assert result.valid is False
        assert result.time_decay_met is False
        assert result.price_decay_met is False
