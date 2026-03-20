"""Unit tests for Delta Volume Profile (Gap #1).

Tests the DeltaProfileAdapter implementation against Fabio AMT spec:
- O(1) per tick incremental update
- High sell delta zones (net_delta < -threshold) = LONG entry zones
- High buy delta zones (net_delta > threshold) = SHORT entry zones
"""

import pytest
from app.infrastructure.adapters.delta_profile_adapter import DeltaProfileAdapter
from app.domain.ports.delta_profile import DeltaBucket, DeltaProfile


class TestDeltaProfileAdapter:
    """Test suite for DeltaProfileAdapter."""

    def test_initial_state_is_empty(self):
        """New adapter should have empty profile."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        assert adapter.get_profile() == []
        assert adapter.bucket_count == 0
        assert adapter.total_volume == 0

    def test_update_creates_bucket(self):
        """First update should create a new bucket."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.0, ask_vol=10, bid_vol=5)
        
        profile = adapter.get_profile()
        assert len(profile) == 1
        assert profile[0].price == 100.0
        assert profile[0].buy_delta == 10
        assert profile[0].sell_delta == 5
        assert profile[0].net_delta == 5
        assert profile[0].total_volume == 15

    def test_update_accumulates_delta(self):
        """Multiple updates to same bucket should accumulate."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.0, ask_vol=10, bid_vol=5)
        adapter.update(price=100.0, ask_vol=20, bid_vol=15)
        
        profile = adapter.get_profile()
        assert len(profile) == 1
        assert profile[0].buy_delta == 30
        assert profile[0].sell_delta == 20
        assert profile[0].net_delta == 10
        assert profile[0].total_volume == 50

    def test_update_creates_multiple_buckets(self):
        """Updates at different prices should create separate buckets."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.0, ask_vol=10, bid_vol=5)
        adapter.update(price=100.1, ask_vol=20, bid_vol=15)
        adapter.update(price=100.2, ask_vol=5, bid_vol=10)
        
        profile = adapter.get_profile()
        assert len(profile) == 3
        # Prices should be sorted (use approximate comparison for float)
        assert abs(profile[0].price - 100.0) < 0.001
        assert abs(profile[1].price - 100.1) < 0.001
        assert abs(profile[2].price - 100.2) < 0.001

    def test_bucket_rounding(self):
        """Prices should round to nearest bucket."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.05, ask_vol=10, bid_vol=5)  # Rounds to 100.0
        adapter.update(price=100.06, ask_vol=10, bid_vol=5)  # Rounds to 100.1
        
        profile = adapter.get_profile()
        assert len(profile) == 2
        assert abs(profile[0].price - 100.0) < 0.001
        assert abs(profile[1].price - 100.1) < 0.001

    def test_get_high_delta_zones_long(self):
        """LONG direction should find high sell delta zones."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        
        # Create a profile with one high sell delta zone
        adapter.update(price=100.0, ask_vol=10, bid_vol=100)  # net = -90
        adapter.update(price=100.1, ask_vol=10, bid_vol=15)   # net = -5
        adapter.update(price=100.2, ask_vol=10, bid_vol=20)   # net = -10
        
        zones = adapter.get_high_delta_zones(direction="LONG", sigma_mult=2.0)
        # 100.0 has net_delta=-90, which is much higher than others
        assert 100.0 in zones

    def test_get_high_delta_zones_short(self):
        """SHORT direction should find high buy delta zones."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        
        # Create a profile with one high buy delta zone
        adapter.update(price=100.0, ask_vol=100, bid_vol=10)  # net = +90
        adapter.update(price=100.1, ask_vol=15, bid_vol=10)   # net = +5
        adapter.update(price=100.2, ask_vol=20, bid_vol=10)   # net = +10
        
        zones = adapter.get_high_delta_zones(direction="SHORT", sigma_mult=2.0)
        # 100.0 has net_delta=+90, which is much higher than others
        assert 100.0 in zones

    def test_get_high_delta_zones_empty(self):
        """Empty profile should return empty zones."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        zones = adapter.get_high_delta_zones(direction="LONG")
        assert zones == []

    def test_get_delta_at_price(self):
        """get_delta_at_price should return correct values."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.0, ask_vol=30, bid_vol=20)
        
        buy, sell, net = adapter.get_delta_at_price(100.0)
        assert buy == 30
        assert sell == 20
        assert net == 10

    def test_get_delta_at_price_missing(self):
        """get_delta_at_price for missing price should return zeros."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        buy, sell, net = adapter.get_delta_at_price(999.0)
        assert buy == 0
        assert sell == 0
        assert net == 0

    def test_reset_clears_state(self):
        """reset() should clear all buckets."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.0, ask_vol=10, bid_vol=5)
        adapter.update(price=100.1, ask_vol=20, bid_vol=15)
        
        adapter.reset()
        
        assert adapter.get_profile() == []
        assert adapter.bucket_count == 0
        assert adapter.total_volume == 0

    def test_zero_price_ignored(self):
        """Zero or negative price should be ignored."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=0.0, ask_vol=10, bid_vol=5)
        adapter.update(price=-1.0, ask_vol=10, bid_vol=5)
        
        assert adapter.get_profile() == []
        assert adapter.bucket_count == 0

    def test_total_volume(self):
        """total_volume should sum all bucket volumes."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        adapter.update(price=100.0, ask_vol=10, bid_vol=5)
        adapter.update(price=100.1, ask_vol=20, bid_vol=15)
        adapter.update(price=100.2, ask_vol=5, bid_vol=10)
        
        assert adapter.total_volume == 15 + 35 + 15  # 65

    def test_bucket_size_property(self):
        """bucket_size property should return configured value."""
        adapter = DeltaProfileAdapter(bucket_size=0.05)
        assert adapter.bucket_size == 0.05

    def test_high_delta_zones_sorted(self):
        """High delta zones should be sorted by price."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        
        # Create multiple high sell delta zones
        adapter.update(price=100.0, ask_vol=10, bid_vol=100)  # net = -90
        adapter.update(price=100.2, ask_vol=10, bid_vol=100)  # net = -90
        adapter.update(price=100.1, ask_vol=10, bid_vol=15)   # net = -5
        
        zones = adapter.get_high_delta_zones(direction="LONG", sigma_mult=1.5)
        # Should be sorted
        assert zones == sorted(zones)

    def test_symmetry_long_short(self):
        """LONG and SHORT should find opposite delta zones."""
        adapter = DeltaProfileAdapter(bucket_size=0.10)
        
        # Create a profile with mixed deltas
        adapter.update(price=100.0, ask_vol=100, bid_vol=10)  # net = +90 (buy pressure)
        adapter.update(price=100.1, ask_vol=10, bid_vol=100)  # net = -90 (sell pressure)
        adapter.update(price=100.2, ask_vol=15, bid_vol=10)   # net = +5
        
        # Use lower sigma_mult to ensure zones are found
        long_zones = adapter.get_high_delta_zones(direction="LONG", sigma_mult=1.0)
        short_zones = adapter.get_high_delta_zones(direction="SHORT", sigma_mult=1.0)
        
        # LONG zones should include high sell delta (100.1) — use approximate comparison
        assert any(abs(z - 100.1) < 0.001 for z in long_zones)
        # SHORT zones should include high buy delta (100.0)
        assert 100.0 in short_zones
        # They should NOT overlap (check with approximate comparison)
        long_set = set(round(z, 1) for z in long_zones)
        short_set = set(round(z, 1) for z in short_zones)
        assert not long_set.intersection(short_set)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])