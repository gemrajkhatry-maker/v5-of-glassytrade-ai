"""Tests for LevelTracker — Second Drive Enforcement (Tasks 17-18)."""
import pytest

from app.domain.fabio_ai.services.level_tracker import (
    LevelTracker,
    TrackedLevel,
    grade_adjustment_for_level_status,
)


class TestLevelTracker:
    def test_first_touch_status(self):
        """Register level at 100.0, price enters proximity -> FIRST_TOUCH."""
        tracker = LevelTracker(proximity_pct=0.003)
        tracker.register_levels([(100.0, "VAH")])
        tracker.update(price=100.0, timestamp=1.0, atr=1.0)
        status = tracker.get_level_status(100.0)
        assert status == ("FIRST_TOUCH", "VAH")

    def test_second_drive_after_pullback(self):
        """First touch, price leaves by 1 ATR, returns -> SECOND_DRIVE."""
        tracker = LevelTracker(proximity_pct=0.003, pullback_atr_mult=1.0)
        tracker.register_levels([(100.0, "POC")])
        atr = 1.0
        # First touch
        tracker.update(price=100.0, timestamp=1.0, atr=atr)
        # Pull back by >= 1 ATR
        tracker.update(price=101.5, timestamp=2.0, atr=atr)
        # Return to level
        tracker.update(price=100.0, timestamp=3.0, atr=atr)
        status = tracker.get_level_status(100.0)
        assert status == ("SECOND_DRIVE", "POC")

    def test_exhausted_after_3_touches(self):
        """3 separate touches with pullbacks -> EXHAUSTED."""
        tracker = LevelTracker(proximity_pct=0.003, pullback_atr_mult=1.0)
        tracker.register_levels([(100.0, "VAL")])
        atr = 1.0
        # Touch 1
        tracker.update(price=100.0, timestamp=1.0, atr=atr)
        # Pullback 1
        tracker.update(price=101.5, timestamp=2.0, atr=atr)
        # Touch 2 -> SECOND_DRIVE
        tracker.update(price=100.0, timestamp=3.0, atr=atr)
        # Pullback 2
        tracker.update(price=101.5, timestamp=4.0, atr=atr)
        # Touch 3 -> EXHAUSTED
        tracker.update(price=100.0, timestamp=5.0, atr=atr)
        status = tracker.get_level_status(100.0)
        assert status == ("EXHAUSTED", "VAL")

    def test_no_drive_without_pullback(self):
        """Price stays near level -> stays FIRST_TOUCH (no pullback = no second drive)."""
        tracker = LevelTracker(proximity_pct=0.003, pullback_atr_mult=1.0)
        tracker.register_levels([(100.0, "HVN")])
        atr = 1.0
        tracker.update(price=100.0, timestamp=1.0, atr=atr)
        # Price stays near, no significant pullback
        tracker.update(price=100.1, timestamp=2.0, atr=atr)
        tracker.update(price=100.0, timestamp=3.0, atr=atr)
        status = tracker.get_level_status(100.0)
        assert status == ("FIRST_TOUCH", "HVN")

    def test_proximity_zone(self):
        """Price within 0.3% -> near, outside -> not near."""
        tracker = LevelTracker(proximity_pct=0.003)
        tracker.register_levels([(1000.0, "VAH")])
        # 0.3% of 1000 = 3.0
        # Within proximity
        tracker.update(price=1002.0, timestamp=1.0, atr=5.0)
        status = tracker.get_level_status(1002.0)
        assert status is not None
        assert status[0] == "FIRST_TOUCH"
        # Outside proximity
        assert tracker.get_level_status(1005.0) is None

    def test_clear_intraday(self):
        """After touches, clear_intraday resets to UNTOUCHED."""
        tracker = LevelTracker(proximity_pct=0.003)
        tracker.register_levels([(100.0, "POC")])
        tracker.update(price=100.0, timestamp=1.0, atr=1.0)
        assert tracker.get_level_status(100.0)[0] == "FIRST_TOUCH"
        tracker.clear_intraday()
        assert tracker.get_level_status(100.0)[0] == "UNTOUCHED"

    def test_register_levels_no_duplicates(self):
        """Registering same level twice doesn't create duplicate."""
        tracker = LevelTracker(proximity_pct=0.003)
        tracker.register_levels([(100.0, "VAH")])
        tracker.register_levels([(100.0, "VAH")])
        # Should only have one level
        assert len(tracker._levels) == 1

    def test_get_level_status_returns_none_far_away(self):
        """Price far from any level -> None."""
        tracker = LevelTracker(proximity_pct=0.003)
        tracker.register_levels([(100.0, "VAH")])
        assert tracker.get_level_status(200.0) is None

    def test_retest_within_proximity_counts(self):
        """Retest 5 ticks below original within proximity counts as touch."""
        tracker = LevelTracker(proximity_pct=0.003)
        level_price = 1000.0
        tracker.register_levels([(level_price, "VAH")])
        atr = 5.0
        # Touch at slightly below level (within 0.3% = 3.0 points)
        tracker.update(price=level_price - 2.0, timestamp=1.0, atr=atr)
        status = tracker.get_level_status(level_price - 2.0)
        assert status is not None
        assert status[0] == "FIRST_TOUCH"


class TestGradeScoreAdjustment:
    def test_second_drive_adds_2(self):
        """SECOND_DRIVE status -> grade_score += 2."""
        assert grade_adjustment_for_level_status("SECOND_DRIVE") == 2

    def test_first_touch_subtracts_1(self):
        """FIRST_TOUCH status -> grade_score -= 1."""
        assert grade_adjustment_for_level_status("FIRST_TOUCH") == -1

    def test_exhausted_subtracts_2(self):
        """EXHAUSTED status -> grade_score -= 2."""
        assert grade_adjustment_for_level_status("EXHAUSTED") == -2

    def test_none_returns_0(self):
        """No level status -> no adjustment."""
        assert grade_adjustment_for_level_status(None) == 0

    def test_untouched_returns_0(self):
        """UNTOUCHED status -> no adjustment."""
        assert grade_adjustment_for_level_status("UNTOUCHED") == 0
