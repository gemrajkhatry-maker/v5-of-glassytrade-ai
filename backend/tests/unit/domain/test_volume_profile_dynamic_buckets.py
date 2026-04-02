"""Tests for Volume Profile dynamic bucket calculation — P1-7."""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from app.domain.services.volume_profile import (
    compute_optimal_buckets,
    create_profile,
    IncrementalVolumeProfile,
)


@dataclass
class MockOHLC:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    taker_buy_volume: float = 0.0
    delta: float = 0.0


class TestComputeOptimalBuckets:
    """Tests for dynamic bucket calculation."""

    def test_nifty_range(self):
        """NIFTY: tick=0.05, range~300pts → capped at 1000."""
        buckets = compute_optimal_buckets(300.0, 0.05)
        assert buckets == 1000  # 6000 ticks → capped

    def test_banknifty_range(self):
        """BANKNIFTY: tick=5, range~1200pts → 240 buckets."""
        buckets = compute_optimal_buckets(1200.0, 5.0)
        assert buckets == 240  # 240 ticks

    def test_crudeoil_range(self):
        """CRUDEOIL: tick=1, range~200pts → 200 buckets."""
        buckets = compute_optimal_buckets(200.0, 1.0)
        assert buckets == 200

    def test_small_range_minimum(self):
        """Very small range → minimum 100 buckets."""
        buckets = compute_optimal_buckets(1.0, 0.05)
        assert buckets == 100  # 20 ticks → minimum 100

    def test_zero_range_fallback(self):
        """Zero range → fallback to 200."""
        assert compute_optimal_buckets(0.0, 0.05) == 200
        assert compute_optimal_buckets(100.0, 0.0) == 200

    def test_large_range_capped(self):
        """Very large range → capped at 1000."""
        buckets = compute_optimal_buckets(10000.0, 0.01)
        assert buckets == 1000  # 1M ticks → capped


class TestCreateProfileDynamicBuckets:
    """Tests for create_profile with auto bucket computation."""

    def test_auto_buckets_from_data(self):
        """Buckets auto-computed when not specified."""
        candles = [
            MockOHLC(f"09:{i:02d}", 24800, 24810, 24790, 24805, 100) for i in range(10)
        ]
        profile = create_profile(candles, buckets=0)  # Auto mode
        assert len(profile) >= 100  # At least minimum
        assert len(profile) <= 1000  # At most maximum

    def test_explicit_buckets_override(self):
        """Explicit bucket count overrides auto-computation."""
        candles = [
            MockOHLC(f"09:{i:02d}", 24800, 24810, 24790, 24805, 100) for i in range(10)
        ]
        profile = create_profile(candles, buckets=50)
        assert len(profile) == 50

    def test_profile_has_levels(self):
        """Profile has meaningful levels."""
        candles = [
            MockOHLC(f"09:{i:02d}", 24800 + i, 24820 + i, 24790 + i, 24805 + i, 100)
            for i in range(20)
        ]
        profile = create_profile(candles, buckets=0)
        assert len(profile) >= 100
        assert all(p.volume >= 0 for p in profile)
        assert any(p.volume > 0 for p in profile)  # At least some volume


class TestIncrementalVolumeProfileDynamic:
    """Tests for IncrementalVolumeProfile with auto bucket computation."""

    def test_auto_buckets_on_rebuild(self):
        """Buckets auto-computed on first rebuild."""
        profile = IncrementalVolumeProfile(buckets=0)  # Auto mode
        candles = [
            MockOHLC(f"09:{i:02d}", 24800, 24820, 24780, 24810, 100) for i in range(5)
        ]
        for c in candles:
            profile.update(c)
        result = profile.get_profile()
        assert len(result) >= 100
        assert len(result) <= 1000

    def test_explicit_buckets_preserved(self):
        """Explicit bucket count is preserved."""
        profile = IncrementalVolumeProfile(buckets=150)
        candles = [
            MockOHLC(f"09:{i:02d}", 24800, 24820, 24780, 24810, 100) for i in range(5)
        ]
        for c in candles:
            profile.update(c)
        result = profile.get_profile()
        assert len(result) == 150

    def test_profile_computes_poc(self):
        """Profile correctly computes POC."""
        profile = IncrementalVolumeProfile(buckets=0)
        # Create candles with volume concentrated at one price
        candles = [
            MockOHLC(f"09:{i:02d}", 24800, 24810, 24790, 24800, 100) for i in range(10)
        ]
        for c in candles:
            profile.update(c)
        result = profile.get_profile()
        assert len(result) > 0
        # Find POC
        poc = max(result, key=lambda p: p.volume)
        assert poc.volume > 0
