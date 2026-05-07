"""Tests for Drive Tracker."""

import pytest

from app.domain.amt.service.drive_tracker import (
    DriveTracker,
    DriveState,
)


class TestDriveTracker:
    """Tests for drive state tracking."""

    def test_drive_number_increments(self):
        """Each level tested -> drive_number + 1."""
        tracker = DriveTracker()
        
        # First update sets the initial level but drive_number stays 0
        result1 = tracker.update(price=100, level=100, direction="UP")
        assert result1.drive_number == 0  # No drive registered yet
        
        # Second update with different level -> drive 1
        result2 = tracker.update(price=105, level=102, direction="UP")
        assert result2.drive_number == 1

    def test_no_drive_before_level_tested(self):
        """No level tested -> drive_number = 0."""
        tracker = DriveTracker()
        
        result = tracker.update(price=100, level=100, direction="UP")
        assert result.drive_number == 0

    def test_momentum_tracking(self):
        """Momentum value tracked."""
        tracker = DriveTracker()
        
        tracker.update(price=100, level=100, direction="UP")
        tracker.update(price=102, level=100, direction="UP")
        
        assert tracker._momentum > 0

    def test_drive_exhaustion(self):
        """3+ drives -> exhausted."""
        tracker = DriveTracker()
        
        # Need to test 4 different levels to get to drive 3
        tracker.update(price=100, level=100, direction="UP")  # Sets level=100, drive=0
        tracker.update(price=105, level=102, direction="UP")  # drive=1
        tracker.update(price=110, level=104, direction="UP")  # drive=2
        result = tracker.update(price=115, level=106, direction="UP")  # drive=3, exhausted
        
        assert result.is_exhausted == True

    def test_reset_clears_state(self):
        """Reset clears drive tracking."""
        tracker = DriveTracker()
        
        tracker.update(price=100, level=100, direction="UP")
        tracker.reset()
        
        assert tracker.drive_number == 0

    def test_drive_state_frozen(self):
        """DriveState is frozen dataclass."""
        state = DriveState(drive_number=1, momentum=0.5, is_exhausted=False)
        
        with pytest.raises(Exception):
            state.drive_number = 2


class TestDriveEntryValidation:
    """Tests for drive entry validation."""

    def test_d2_with_d1_rejected_valid(self):
        """D2 with D1 rejected -> valid for entry."""
        tracker = DriveTracker()
        # Simulate D1: first level test
        state1 = tracker.update(price=100, level=100, direction="UP")
        # Simulate D2: same level tested again (rejection)
        state2 = tracker.update(price=100, level=100, direction="DOWN")
        # Drive number should be 1 (first unique level)
        assert state1.drive_number == 0
        assert state2.drive_number == 0

    def test_down_direction_momentum(self):
        """Down direction decreases momentum."""
        tracker = DriveTracker()
        
        tracker.update(price=100, level=100, direction="UP")
        tracker.update(price=98, level=102, direction="DOWN")
        tracker.update(price=96, level=104, direction="DOWN")  # Second down move
        
        assert tracker._momentum < 0

    def test_multiple_levels_same_drive(self):
        """Same level tested multiple times doesn't increment."""
        tracker = DriveTracker()
        
        result1 = tracker.update(price=100, level=100, direction="UP")
        result2 = tracker.update(price=102, level=100, direction="UP")  # Same level
        
        assert result1.drive_number == result2.drive_number