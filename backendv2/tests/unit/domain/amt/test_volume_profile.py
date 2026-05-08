"""Tests for volume profile construction and VWAP calculation."""

import pytest
from app.domain.amt.service.volume_profile import build_volume_profile, calculate_vwap
from app.domain.amt.model.amt_models import VolumeProfileLevel


class TestBuildVolumeProfile:
    """Tests for volume profile construction."""

    def test_returns_empty_for_no_bars(self):
        """Should return empty profile when no bars provided."""
        profile = build_volume_profile([], bucket_size=1.0)
        
        assert len(profile.levels) == 0
        assert profile.poc == 0.0
        assert profile.vah == 0.0
        assert profile.val == 0.0
        assert profile.step == 1.0

    def test_builds_profile_from_single_bar(self):
        """Should build profile from single bar."""
        bars = [
            {"low": 100.0, "high": 101.0, "volume": 1000, "buyVolume": 600, "sellVolume": 400}
        ]
        
        profile = build_volume_profile(bars, bucket_size=1.0)
        
        assert len(profile.levels) >= 1
        assert profile.poc > 0
        assert profile.vah > 0
        assert profile.val > 0

    def test_identifies_poc_correctly(self):
        """Should identify Point of Control as highest volume level."""
        bars = [
            {"low": 100.0, "high": 101.0, "volume": 100},  # Low volume
            {"low": 102.0, "high": 103.0, "volume": 5000}, # High volume (POC)
            {"low": 104.0, "high": 105.0, "volume": 200},  # Low volume
        ]
        
        profile = build_volume_profile(bars, bucket_size=1.0)
        
        # POC should be around 102-103 (highest volume)
        assert profile.poc >= 102.0
        assert profile.poc <= 103.0

    def test_calculates_value_area(self):
        """Should calculate Value Area High and Low."""
        bars = [
            {"low": 100.0, "high": 101.0, "volume": 1000},
            {"low": 101.0, "high": 102.0, "volume": 2000},
            {"low": 102.0, "high": 103.0, "volume": 5000},  # POC
            {"low": 103.0, "high": 104.0, "volume": 2000},
            {"low": 104.0, "high": 105.0, "volume": 1000},
        ]
        
        profile = build_volume_profile(bars, bucket_size=1.0)
        
        # VAH should be >= POC
        assert profile.vah >= profile.poc
        # VAL should be <= POC
        assert profile.val <= profile.poc
        # VAH should be >= VAL
        assert profile.vah >= profile.val

    def test_uses_correct_bucket_size(self):
        """Should respect bucket_size parameter."""
        bars = [
            {"low": 100.0, "high": 110.0, "volume": 1000}
        ]
        
        profile = build_volume_profile(bars, bucket_size=5.0)
        
        assert profile.step == 5.0

    def test_aggregates_buy_sell_volume(self):
        """Should track buy and sell volume separately."""
        bars = [
            {"low": 100.0, "high": 101.0, "volume": 1000, "buyVolume": 600, "sellVolume": 400}
        ]
        
        profile = build_volume_profile(bars, bucket_size=1.0)
        
        # Check that levels have buy/sell volume
        for level in profile.levels:
            assert level.buy_volume >= 0
            assert level.sell_volume >= 0

    def test_handles_zero_range_bar(self):
        """Should skip bars with zero range."""
        bars = [
            {"low": 100.0, "high": 100.0, "volume": 1000},  # Zero range
            {"low": 101.0, "high": 102.0, "volume": 1000},  # Valid
        ]
        
        profile = build_volume_profile(bars, bucket_size=1.0)
        
        # Should still build profile from valid bar
        assert len(profile.levels) >= 1

    def test_sorts_levels_by_price(self):
        """Should return levels sorted by price."""
        bars = [
            {"low": 105.0, "high": 106.0, "volume": 1000},
            {"low": 100.0, "high": 101.0, "volume": 1000},
            {"low": 103.0, "high": 104.0, "volume": 1000},
        ]
        
        profile = build_volume_profile(bars, bucket_size=1.0)
        
        prices = [level.price for level in profile.levels]
        assert prices == sorted(prices)

    def test_volume_distributed_across_all_buckets_not_just_edges(self):
        """Volume should be distributed across the bar's price range, not just at low/high endpoints.
        
        This is a critical bug fix: the original implementation only assigned volume
        to bar_low and bar_high, effectively doubling volume attribution and placing
        POC at edges instead of the true maximum volume price.
        """
        bars = [
            {"low": 90.0, "high": 110.0, "close": 100.0, "volume": 1000, "buyVolume": 500, "sellVolume": 500}
        ]
        
        profile = build_volume_profile(bars, bucket_size=5.0)
        
        # Volume should appear in buckets: 90, 95, 100, 105, 110 (5+ buckets)
        # NOT just at 90 and 110 (2 buckets)
        active_buckets = [level for level in profile.levels if level.volume > 0]
        assert len(active_buckets) >= 5, (
            f"Expected volume in 5+ buckets across the range, got {len(active_buckets)}. "
            f"Volume should be distributed across all price buckets, not just edges."
        )
        
        # Total volume should equal the bar's volume (not doubled)
        total_volume = sum(level.volume for level in profile.levels)
        assert total_volume == pytest.approx(1000, rel=0.01), (
            f"Total volume should equal bar volume (1000), got {total_volume}. "
            f"Volume is being double-counted at edges."
        )


class TestCalculateVWAP:
    """Tests for VWAP calculation."""

    def test_returns_zeros_for_no_bars(self):
        """Should return zeros when no bars provided."""
        vwap, u1, l1, u2, l2 = calculate_vwap([])
        
        assert vwap == 0.0
        assert u1 == 0.0
        assert l1 == 0.0
        assert u2 == 0.0
        assert l2 == 0.0

    def test_calculates_basic_vwap(self):
        """Should calculate VWAP from typical prices."""
        bars = [
            {"high": 100.0, "low": 99.0, "close": 99.5, "volume": 1000},
        ]
        
        vwap, u1, l1, u2, l2 = calculate_vwap(bars)
        
        # Typical price = (100 + 99 + 99.5) / 3 = 99.5
        assert vwap == pytest.approx(99.5, rel=0.01)

    def test_vwap_with_multiple_bars(self):
        """Should calculate weighted VWAP across multiple bars."""
        bars = [
            {"high": 100.0, "low": 99.0, "close": 99.5, "volume": 1000},
            {"high": 102.0, "low": 101.0, "close": 101.5, "volume": 2000},  # More volume
        ]
        
        vwap, u1, l1, u2, l2 = calculate_vwap(bars)
        
        # VWAP should be closer to second bar's typical price (more volume)
        assert vwap > 100.0
        assert vwap < 101.5

    def test_calculates_standard_deviation_bands(self):
        """Should calculate 1σ and 2σ bands."""
        bars = [
            {"high": 100.0, "low": 99.0, "close": 99.5, "volume": 1000},
            {"high": 102.0, "low": 101.0, "close": 101.5, "volume": 1000},
        ]
        
        vwap, u1, l1, u2, l2 = calculate_vwap(bars)
        
        # Bands should be ordered correctly
        assert l2 < l1 < vwap < u1 < u2
        # 2σ should be further from VWAP than 1σ
        assert (u2 - vwap) > (u1 - vwap)
        assert (vwap - l2) > (vwap - l1)

    def test_handles_zero_volume(self):
        """Should return zeros when all volume is zero."""
        bars = [
            {"high": 100.0, "low": 99.0, "close": 99.5, "volume": 0},
        ]
        
        vwap, u1, l1, u2, l2 = calculate_vwap(bars)
        
        assert vwap == 0.0
        assert u1 == 0.0
        assert l1 == 0.0
        assert u2 == 0.0
        assert l2 == 0.0

    def test_vwap_increases_with_higher_prices(self):
        """Should increase VWAP when prices trend up."""
        bars_low = [
            {"high": 100.0, "low": 99.0, "close": 99.5, "volume": 1000},
        ]
        bars_high = [
            {"high": 110.0, "low": 109.0, "close": 109.5, "volume": 1000},
        ]

        vwap_low, _, _, _, _ = calculate_vwap(bars_low)
        vwap_high, _, _, _, _ = calculate_vwap(bars_high)

        assert vwap_high > vwap_low


class TestVolumeProfileValueAreaPct:
    def test_value_area_uses_70_percent_by_default(self):
        """Default value_area_pct should be 0.70 (70%), not 0.68."""
        bars = [
            {"high": 100.0, "low": 90.0, "close": 95.0, "volume": 100},
        ]
        vp = build_volume_profile(bars, bucket_size=1.0)
        total_volume = sum(l.volume for l in vp.levels)
        va_volume = sum(
            l.volume for l in vp.levels
            if min(vp.val, vp.vah) <= l.price <= max(vp.val, vp.vah)
        )
        # Value area should contain approximately 70% of total volume
        assert va_volume >= total_volume * 0.69  # Allow small rounding

    def test_value_area_respects_custom_pct(self):
        """Custom value_area_pct should be respected."""
        bars = [
            {"high": 100.0, "low": 90.0, "close": 95.0, "volume": 100},
        ]
        vp_narrow = build_volume_profile(bars, bucket_size=1.0, value_area_pct=0.50)
        vp_wide = build_volume_profile(bars, bucket_size=1.0, value_area_pct=0.90)
        # Wider value area should encompass more price range
        assert (vp_wide.vah - vp_wide.val) >= (vp_narrow.vah - vp_narrow.val)


class TestPOCTieBreaking:
    def test_poc_tie_breaking_selects_median_price(self):
        """When two buckets share max volume, pick the one closest to median price."""
        bars = [
            {"high": 102.0, "low": 100.0, "close": 101.0, "volume": 100},
        ]
        vp = build_volume_profile(bars, bucket_size=2.0)
        # Both buckets (100, 102) have equal volume; POC should be median (101)
        # With bucket_size=2.0, buckets are at 100 and 102
        # Median = (100 + 102) / 2 = 101, both equally distant
        # max() returns first, so POC = 100
        assert vp.poc in (100.0, 102.0)

    def test_poc_no_tie_break_when_unique_max(self):
        """When one bucket clearly has max volume, no tie-breaking needed."""
        bars = [
            {"high": 101.0, "low": 100.0, "close": 100.5, "volume": 100},
            {"high": 103.0, "low": 102.0, "close": 102.5, "volume": 10},
        ]
        vp = build_volume_profile(bars, bucket_size=1.0)
        # Bucket at 100-101 has much more volume
        assert vp.poc >= 100.0 and vp.poc < 102.0


class TestTickAlignment:
    def test_bucket_boundaries_aligned_to_tick_size(self):
        """All bucket prices should be on tick boundaries."""
        bars = [
            {"high": 100.37, "low": 99.83, "close": 100.10, "volume": 100},
        ]
        vp = build_volume_profile(bars, bucket_size=1.0, tick_size=0.05)
        for level in vp.levels:
            # Price should be aligned to 0.05 tick
            remainder = level.price / 0.05
            assert abs(remainder - round(remainder)) < 1e-9
