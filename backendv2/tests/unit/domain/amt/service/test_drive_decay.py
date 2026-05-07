"""Tests for DriveDecay — Time/Price rotation enforcement per Fabio AMT spec."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.domain.amt.service.drive_decay import DriveDecay, DriveDecayResult


def _make_time(hour: int, minute: int) -> datetime:
    return datetime(2024, 1, 1, hour, minute, 0, tzinfo=timezone.utc)


class TestRecordDrive1:
    """Tests for recording Drive 1."""

    def test_record_drive_1_stores_level(self):
        """Drive 1 record is stored for a level."""
        decay = DriveDecay()
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        # Validate Drive 2 should find the record but fail decay
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 31))
        assert result.valid is False  # Neither time nor price decay met
        assert "No Drive 1" not in result.reason

    def test_record_drive_1_with_different_levels(self):
        """Multiple levels can be tracked independently."""
        decay = DriveDecay()
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        decay.record_drive_1(level=200.0, direction="SHORT", timestamp=_make_time(9, 30), tick_size=0.05)

        result1 = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 31))
        result2 = decay.validate_drive_2(level=200.0, current_price=200.0, current_time=_make_time(9, 31))
        # Both should have records (not "No Drive 1" reason)
        assert "No Drive 1" not in result1.reason
        assert "No Drive 1" not in result2.reason


class TestTimeDecay:
    """Tests for time-based decay."""

    def test_time_decay_met_after_min_minutes(self):
        """Time decay satisfied when >= min_minutes have passed."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 33))
        assert result.time_decay_met is True
        assert result.valid is True

    def test_time_decay_not_met_before_min_minutes(self):
        """Time decay not satisfied when < min_minutes have passed."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 32))
        assert result.time_decay_met is False


class TestPriceDecay:
    """Tests for price rotation-based decay."""

    def test_price_decay_met_with_sufficient_rotation(self):
        """Price decay satisfied when rotation >= min_ticks * tick_size."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        # Rotation of 0.20 >= 3 * 0.05 = 0.15
        decay.update_rotation(100.20)
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 31))
        assert result.price_decay_met is True
        assert result.valid is True

    def test_price_decay_not_met_with_insufficient_rotation(self):
        """Price decay not satisfied when rotation < min_ticks * tick_size."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        # Rotation of 0.05 < 3 * 0.05 = 0.15
        decay.update_rotation(100.05)
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 31))
        assert result.price_decay_met is False
        assert result.valid is False


class TestValidateDrive2:
    """Tests for Drive 2 validation edge cases."""

    def test_no_drive_1_record_returns_invalid(self):
        """Validate Drive 2 without Drive 1 record returns invalid."""
        decay = DriveDecay()
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 30))
        assert result.valid is False
        assert result.time_decay_met is False
        assert result.price_decay_met is False
        assert "No Drive 1" in result.reason


class TestLevelClearing:
    """Tests for level clearing and reset."""

    def test_clear_level_removes_record(self):
        """Clearing a level removes its Drive 1 record."""
        decay = DriveDecay()
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        decay.clear_level(100.0, tick_size=0.05)
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 31))
        assert result.valid is False
        assert "No Drive 1" in result.reason

    def test_reset_clears_all_records(self):
        """Reset clears all Drive 1 records."""
        decay = DriveDecay()
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        decay.record_drive_1(level=200.0, direction="SHORT", timestamp=_make_time(9, 30), tick_size=0.05)
        decay.reset()
        result1 = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 31))
        result2 = decay.validate_drive_2(level=200.0, current_price=200.0, current_time=_make_time(9, 31))
        assert "No Drive 1" in result1.reason
        assert "No Drive 1" in result2.reason


class TestBothConditionsMet:
    """Tests for when both time and price decay are met."""

    def test_both_time_and_price_decay_met(self):
        """Both conditions satisfied returns valid with combined reason."""
        decay = DriveDecay(min_ticks=3, min_minutes=3)
        decay.record_drive_1(level=100.0, direction="LONG", timestamp=_make_time(9, 30), tick_size=0.05)
        decay.update_rotation(100.20)
        result = decay.validate_drive_2(level=100.0, current_price=100.0, current_time=_make_time(9, 33))
        assert result.time_decay_met is True
        assert result.price_decay_met is True
        assert result.valid is True
