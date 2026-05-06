"""Second drive detection tests - TDD cycle 2.2 (testing existing implementation)."""
import pytest
from app.domain.amt.service.regime_detector import RegimeDetector


class TestSecondDriveDetection:
    """Test Fabio's second drive enforcement: wait for pullback before entering."""

    def test_detects_second_drive_after_pullback(self):
        """Should detect second drive when price returns to level after retreating."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # First touch at 100.0
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        
        # Price retreats >0.5% away
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Price returns to level = second drive
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True

    def test_no_second_drive_without_pullback(self):
        """Should NOT detect second drive if price never retreated from level."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # Price stays near level (no retreat)
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=100.1, key_levels=key_levels, timestamp=2.0)
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=3.0)
        
        # No second drive (never retreated)
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is False

    def test_first_touch_not_second_drive(self):
        """Should NOT detect second drive on first touch."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # First touch only
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is False

    def test_second_drive_requires_03_percent_proximity(self):
        """Should only detect second drive when price within 0.3% of level."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # First touch and retreat
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Price near level (0.3% = 0.3 points for 100.0)
        assert detector.is_second_drive(price=100.2, key_levels=key_levels) is True
        
        # Price outside proximity (0.4% = 0.4 points)
        assert detector.is_second_drive(price=100.4, key_levels=key_levels) is False

    def test_pullback_requires_05_percent_away(self):
        """Should only mark as retreated when price moves >0.5% away."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # First touch
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        
        # Price moves 0.4% away (not enough for retreat)
        detector.record_level_approach(price=100.4, key_levels=key_levels, timestamp=2.0)
        
        # Price returns - should NOT be second drive (never retreated)
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is False
        
        # Price moves 0.6% away (enough for retreat)
        detector.record_level_approach(price=100.6, key_levels=key_levels, timestamp=3.0)
        
        # Now should be second drive
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True

    def test_tracks_multiple_levels_independently(self):
        """Should track second drive for multiple levels independently."""
        detector = RegimeDetector()
        
        key_levels = [100.0, 105.0]
        
        # Touch 100.0 and retreat
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Touch 105.0 (first touch only)
        detector.record_level_approach(price=105.0, key_levels=key_levels, timestamp=3.0)
        
        # 100.0 should be second drive, 105.0 should not
        assert detector.is_second_drive(price=100.0, key_levels=[100.0]) is True
        assert detector.is_second_drive(price=105.0, key_levels=[105.0]) is False

    def test_ignores_invalid_levels(self):
        """Should ignore zero or negative levels."""
        detector = RegimeDetector()
        
        key_levels = [0.0, -100.0, 100.0]
        
        # Touch valid level
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Should detect second drive for valid level
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True

    def test_caps_level_touches_at_100(self):
        """Should cap level touches at 100 to prevent unbounded growth."""
        detector = RegimeDetector()
        
        # Add 105 different levels
        for i in range(105):
            level = 100.0 + i
            detector.record_level_approach(
                price=level, key_levels=[level], timestamp=float(i)
            )
            # Retreat
            detector.record_level_approach(
                price=level + 1.0, key_levels=[level], timestamp=float(i + 0.5)
            )
        
        # Should have capped at 100
        assert len(detector._level_touches) <= 100

    def test_second_drive_with_exact_threshold(self):
        """Should detect second drive at exact 0.3% proximity threshold."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # First touch and retreat
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Exactly 0.3% away (boundary)
        assert detector.is_second_drive(price=100.3, key_levels=key_levels) is True

    def test_second_drive_beyond_threshold(self):
        """Should NOT detect second drive beyond 0.3% proximity."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # First touch and retreat
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Beyond 0.3% (0.31%)
        assert detector.is_second_drive(price=100.31, key_levels=key_levels) is False

    def test_multiple_touches_same_level(self):
        """Should handle multiple touches of same level correctly."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # Touch 1
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Second drive detected
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True
        
        # Touch again (should still work)
        detector.record_level_approach(price=100.5, key_levels=key_levels, timestamp=3.0)
        detector.record_level_approach(price=101.5, key_levels=key_levels, timestamp=4.0)
        
        # Still second drive
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True

    def test_float_precision_bucketing(self):
        """Should use bucketing to avoid float precision issues."""
        detector = RegimeDetector()
        
        # Use level that rounds cleanly to 1 decimal (is_second_drive uses round(level, 1))
        key_levels = [100.1]
        
        # Touch with slight float variation
        detector.record_level_approach(price=100.1, key_levels=key_levels, timestamp=1.0)
        detector.record_level_approach(price=101.1, key_levels=key_levels, timestamp=2.0)
        
        # Should detect second drive (bucketed correctly)
        assert detector.is_second_drive(price=100.1, key_levels=key_levels) is True

    def test_integration_with_regime_detector(self):
        """Should integrate seamlessly with RegimeDetector state."""
        detector = RegimeDetector()
        
        # Test with single level for clarity
        key_levels = [100.0]
        
        # Simulate trading session
        # Initial touch at 100.0
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        
        # NOT second drive yet (first touch)
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is False
        
        # Move away (retreat)
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # NOW second drive
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True

    def test_round_trip_no_false_positives(self):
        """Should have no false positives in complete round-trip scenario."""
        detector = RegimeDetector()
        
        key_levels = [100.0]
        
        # NOT second drive: first touch
        detector.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is False
        
        # NOT second drive: still near level (no retreat)
        detector.record_level_approach(price=100.2, key_levels=key_levels, timestamp=2.0)
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is False
        
        # Retreat
        detector.record_level_approach(price=101.0, key_levels=key_levels, timestamp=3.0)
        
        # NOW second drive: returned after retreat
        assert detector.is_second_drive(price=100.0, key_levels=key_levels) is True
        
        # Still second drive if we check again
        assert detector.is_second_drive(price=100.1, key_levels=key_levels) is True
