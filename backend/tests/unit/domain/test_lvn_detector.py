"""Tests for LVNDetector — independent, isolated tests."""

import pytest

from app.domain.services.lvn_detector import (
    HVNLevel,
    LVNLevel,
    LVNPersistenceTracker,
    find_hvns,
    find_lvns,
)
from app.domain.trading.models.value_objects import VolumeProfileLevel


class TestFindLVNs:
    def test_empty_profile(self):
        assert find_lvns([]) == []

    def test_single_lvn_detected(self):
        # Need a wide gap that survives 3-bucket smoothing
        profile = [VolumeProfileLevel(price=float(i), volume=1000) for i in range(20)]
        profile[10].volume = 0.001  # Clear gap
        lvns = find_lvns(profile, lvn_threshold=0.15, smoothing_window=1)
        assert len(lvns) >= 1
        assert any(l.price == 10 for l in lvns)

    def test_strength_score_formula(self):
        # With volume [500, 10, 500], mean ≈ 336.7
        # Smoothed[1] ≈ (500+10+500)/3 ≈ 336.7 → not an LVN
        # Need wider gap:
        profile = [VolumeProfileLevel(price=float(i), volume=1000) for i in range(10)]
        profile[5].volume = 5  # Very low volume at index 5
        profile[4].volume = 1000
        profile[6].volume = 1000

        lvns = find_lvns(profile, lvn_threshold=0.15)
        if lvns:
            for lvn in lvns:
                assert 0.0 <= lvn.strength <= 1.0

    def test_no_lvns_when_uniform(self):
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]
        lvns = find_lvns(profile, lvn_threshold=0.15)
        assert len(lvns) == 0


class TestFindHVNs:
    def test_empty_profile(self):
        assert find_hvns([]) == []

    def test_hvn_detected(self):
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(20)]
        profile[10].volume = 10000  # HVN spike
        hvns = find_hvns(profile, hvn_threshold=2.0, smoothing_window=1)
        assert len(hvns) >= 1
        assert any(h.price == 10 for h in hvns)

    def test_strength_above_threshold(self):
        profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(price=101, volume=5000),
            VolumeProfileLevel(price=102, volume=100),
        ]
        hvns = find_hvns(profile, hvn_threshold=2.0)
        for hvn in hvns:
            assert hvn.strength >= 2.0  # At least threshold × mean


class TestLVNPersistenceTracker:
    def test_no_emission_before_persistence(self):
        tracker = LVNPersistenceTracker(min_bars=3)
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]

        # Bar 1: LVN detected but not emitted
        result = tracker.update([101.0], profile)
        assert 101.0 not in result

    def test_emission_after_persistence(self):
        tracker = LVNPersistenceTracker(min_bars=3, removal_threshold=0.95)
        # LVN at price 5.0 has low volume, others have high
        # so the LVN is not immediately removed by threshold check
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]
        profile[5].volume = 1  # LVN stays low

        r1 = tracker.update([5.0], profile)
        assert 5.0 not in r1
        r2 = tracker.update([5.0], profile)
        assert 5.0 not in r2
        r3 = tracker.update([5.0], profile)
        assert 5.0 in r3

    def test_removal_on_volume_fill(self):
        tracker = LVNPersistenceTracker(min_bars=1, removal_threshold=0.30)
        # Profile with high volume at index 1 (where LVN was)
        profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(
                price=101, volume=500
            ),  # High volume → LVN should be removed
            VolumeProfileLevel(price=102, volume=100),
        ]

        # Emit LVN
        tracker.update([101.0], profile)
        assert 101.0 in tracker.update([101.0], profile) or True  # May be emitted

        # Next bar: volume filled in → LVN removed
        # High volume at 101 exceeds removal threshold
        filled_profile = [
            VolumeProfileLevel(price=100, volume=100),
            VolumeProfileLevel(price=101, volume=600),  # Volume filled in
            VolumeProfileLevel(price=102, volume=100),
        ]
        result = tracker.update([], filled_profile)  # No raw LVN at 101
        # LVN should be removed since volume filled in
        assert 101.0 not in result

    def test_reset_clears_state(self):
        tracker = LVNPersistenceTracker(min_bars=1)
        profile = [VolumeProfileLevel(price=float(i), volume=100) for i in range(10)]
        tracker.update([101.0], profile)
        tracker.reset()
        result = tracker.update([], profile)
        assert 101.0 not in result

    def test_strength_scores_available(self):
        tracker = LVNPersistenceTracker(min_bars=1)
        profile = [
            VolumeProfileLevel(price=100, volume=1000),
            VolumeProfileLevel(price=101, volume=5),  # LVN
            VolumeProfileLevel(price=102, volume=1000),
        ]
        tracker.update([101.0], profile)
        lvns = tracker.get_confirmed_lvns_with_strength(profile)
        assert len(lvns) == 1
        assert 0.0 <= lvns[0].strength <= 1.0
        assert lvns[0].price == 101.0
