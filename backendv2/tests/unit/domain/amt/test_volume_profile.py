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
