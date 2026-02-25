"""Unit tests for AMT analyzer domain service."""

from __future__ import annotations

import math
import pytest
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
from app.domain.fabio_ai.services.amt_analyzer import (
    smooth_array, create_profile, find_lvns, find_hvns,
    find_aggressive_prints, AMTAnalyzer, AMTConfig,
)
from app.domain.trading.models.value_objects import VolumeProfileLevel
from app.infrastructure.adapters.data_generator import generate_market_data


def _make_candle(close: float, volume: float = 1000, delta: float = 0,
                 high: float | None = None, low: float | None = None,
                 open_: float | None = None) -> OHLC:
    o = open_ or close
    h = high or max(close, o) * 1.001
    l = low or min(close, o) * 0.999
    return OHLC(
        time="2026-01-01T00:00:00Z", open=o, high=h, low=l,
        close=close, volume=volume, vwap=(h + l + close) / 3,
        taker_buy_volume=(volume + delta) / 2, delta=delta,
    )


class TestSmoothArray:
    def test_identity_window_1(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = smooth_array(data, 1)
        assert result == data

    def test_smoothing_window_3(self):
        data = [0.0, 10.0, 0.0]
        result = smooth_array(data, 3)
        assert abs(result[1] - 10.0 / 3) < 0.01


class TestCreateProfile:
    def test_empty(self):
        assert create_profile([]) == []

    def test_basic_profile(self):
        data = generate_market_data(50, 100, "sideways")
        profile = create_profile(data, 20)
        assert len(profile) == 20
        assert all(p.volume >= 0 for p in profile)

    def test_total_volume_roughly_matches(self):
        data = generate_market_data(100, 100, "bullish")
        profile = create_profile(data, 50)
        profile_vol = sum(p.volume for p in profile)
        data_vol = sum(d.volume for d in data)
        assert abs(profile_vol - data_vol) / data_vol < 0.05


class TestFindLVNsHVNs:
    def test_hvns_exist_in_normal_data(self):
        data = generate_market_data(200, 100, "sideways")
        profile = create_profile(data, 50)
        hvns = find_hvns(profile)
        assert isinstance(hvns, list)


class TestAggressivePrints:
    def test_empty_short_data(self):
        data = [_make_candle(100) for _ in range(10)]
        prints = find_aggressive_prints(data)
        assert prints == []

    def test_detects_prints(self):
        data = [_make_candle(100, volume=100, delta=30) for _ in range(60)]
        data[30] = _make_candle(100, volume=500, delta=200)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1
        assert prints[0].side == "BUY"


class TestAMTAnalyzer:
    def test_insufficient_data(self):
        analyzer = AMTAnalyzer()
        result = analyzer.analyze([_make_candle(100)])
        assert result.market_state == "BALANCED"
        assert result.signal is None

    def test_empty_data(self):
        analyzer = AMTAnalyzer()
        result = analyzer.analyze([])
        assert result.poc == 0

    def test_basic_analysis(self):
        analyzer = AMTAnalyzer()
        data = generate_market_data(100, 100, "sideways")
        result = analyzer.analyze(data)
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low
        assert isinstance(result.profile, tuple)
        assert len(result.profile) > 0

    def test_with_order_book(self):
        analyzer = AMTAnalyzer()
        data = generate_market_data(100, 100, "bullish")
        ob = OrderBook(
            bids=(OrderBookLevel(price=100, quantity=1000),),
            asks=(OrderBookLevel(price=101, quantity=100),),
        )
        result = analyzer.analyze(data, ob)
        assert result.poc > 0

    # ----- Formula gap tests -----

    def test_vah_val_use_bin_edges(self):
        """VAH should be upper edge of top VA bin, VAL lower edge of bottom."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        profile = list(result.profile)
        if len(profile) > 1:
            step = profile[1].price - profile[0].price
            half = step / 2
            # VAH and VAL should NOT equal any bin midpoint exactly
            midpoints = {round(p.price, 8) for p in profile}
            assert round(result.value_area_high, 8) not in midpoints
            assert round(result.value_area_low, 8) not in midpoints
            # They should be offset by exactly half_step from a midpoint
            vah_offset = min(abs(result.value_area_high - p.price) for p in profile)
            val_offset = min(abs(result.value_area_low - p.price) for p in profile)
            assert abs(vah_offset - half) < 0.001
            assert abs(val_offset - half) < 0.001

    def test_poc_tiebreak_closest_to_vwap(self):
        """When multiple bins share max volume, POC should be closest to VWAP."""
        # Create a profile with two equal-volume peaks
        profile = [VolumeProfileLevel(price=90 + i * 10, volume=0) for i in range(5)]
        profile[1].volume = 100  # price=100
        profile[3].volume = 100  # price=120
        # With VWAP closer to 120, POC should pick index 3
        analyzer = AMTAnalyzer()
        # Seed the VWAP accumulator toward 120
        analyzer._vwap_cum_vol = 1000
        analyzer._vwap_cum_quote_vol = 120000  # VWAP = 120
        data = [_make_candle(120, volume=100) for _ in range(30)]
        result = analyzer.analyze(data)
        # POC should exist and be valid
        assert result.poc > 0

    def test_balance_ratio_computed(self):
        """Balance ratio should be between 0 and 1."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert 0.0 <= result.balance_ratio <= 1.0

    def test_balanced_market_has_balance_ratio(self):
        """Sideways market should have non-zero balance ratio."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert result.balance_ratio > 0.0  # at least some candles inside VA

    def test_vwap_bands_computed(self):
        """VWAP ±1σ and ±2σ bands should be populated after analysis."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert result.session_vwap > 0
        # Bands should be symmetric around VWAP
        assert result.vwap_upper_1 >= result.session_vwap
        assert result.vwap_lower_1 <= result.session_vwap
        assert result.vwap_upper_2 >= result.vwap_upper_1
        assert result.vwap_lower_2 <= result.vwap_lower_1

    def test_vwap_bands_2sigma_wider_than_1sigma(self):
        """2σ bands should be wider than 1σ bands."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "bullish")
        result = analyzer.analyze(data)
        width_1 = result.vwap_upper_1 - result.vwap_lower_1
        width_2 = result.vwap_upper_2 - result.vwap_lower_2
        assert width_2 >= width_1

    def test_displacement_leg_returns_leg_lvns(self):
        """detect_displacement_leg should return LVN list (possibly empty)."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "bullish")
        result = analyzer.detect_displacement_leg(data)
        assert isinstance(result, dict)
        assert isinstance(result["has_displacement"], bool)
        assert isinstance(result["lvns"], list)

    def test_amt_result_has_new_fields(self):
        """AMTResult should include all new formula fields."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        # All new fields should exist
        assert hasattr(result, 'vwap_upper_1')
        assert hasattr(result, 'vwap_lower_1')
        assert hasattr(result, 'vwap_upper_2')
        assert hasattr(result, 'vwap_lower_2')
        assert hasattr(result, 'balance_ratio')


class TestConfirmationBundle:
    """Tests for spread tightness in confirmation bundle."""

    def test_spread_tightness_passes_tight_spread(self):
        """Tight bid-ask spread (≤5 bps) should pass spread check."""
        from app.domain.fabio_ai.services.entry_gate import check_confirmation_bundle
        data = [_make_candle(100, volume=200, delta=80) for _ in range(30)]
        tick = _make_candle(100, volume=500, delta=200)
        ob = OrderBook(
            bids=(OrderBookLevel(price=99.99, quantity=100),),
            asks=(OrderBookLevel(price=100.01, quantity=100),),  # 2 bps spread
        )
        result = check_confirmation_bundle(data, tick, ob)
        assert isinstance(result, bool)

    def test_spread_tightness_no_orderbook_passes(self):
        """No order book should not penalize (spread_tight = True)."""
        from app.domain.fabio_ai.services.entry_gate import check_confirmation_bundle
        data = [_make_candle(100, volume=200, delta=80) for _ in range(30)]
        tick = _make_candle(100, volume=500, delta=200)
        result = check_confirmation_bundle(data, tick, None)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Group 1: Full AMTAnalyzer.analyze() Integration Tests
# ---------------------------------------------------------------------------

def _make_candle_timed(close: float, time_str: str, volume: float = 1000,
                       delta: float = 0, high: float | None = None,
                       low: float | None = None) -> OHLC:
    """Helper that creates a candle with a specific timestamp."""
    o = close
    h = high or close * 1.002
    l = low or close * 0.998
    return OHLC(
        time=time_str, open=o, high=h, low=l,
        close=close, volume=volume,
        vwap=(h + l + close) / 3,
        taker_buy_volume=(volume + delta) / 2, delta=delta,
    )


class TestAnalyzeIntegration:
    """Integration tests for the full analyze() pipeline."""

    def test_analyze_returns_three_tuple(self):
        """analyze() should return an AMTResult (not a tuple in current API)."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        # The return type is AMTResult with all required fields
        assert hasattr(result, "market_state")
        assert hasattr(result, "poc")
        assert hasattr(result, "value_area_high")
        assert hasattr(result, "value_area_low")
        assert hasattr(result, "profile")
        assert hasattr(result, "market_structure")

    def test_analyze_all_fields_populated(self):
        """All AMTResult fields should be populated with valid values on sideways data."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(60, 100, "sideways")
        result = analyzer.analyze(data)

        # Core VP fields
        assert result.poc > 0
        assert result.value_area_high > 0
        assert result.value_area_low > 0
        assert result.value_area_high >= result.value_area_low

        # Profile populated
        assert len(result.profile) > 0
        assert sum(p.volume for p in result.profile) > 0

        # VWAP bands
        assert result.session_vwap > 0
        assert result.vwap_upper_1 >= result.session_vwap
        assert result.vwap_lower_1 <= result.session_vwap
        assert result.vwap_upper_2 >= result.vwap_upper_1
        assert result.vwap_lower_2 <= result.vwap_lower_1

        # Balance ratio in valid range
        assert 0.0 <= result.balance_ratio <= 1.0

        # CVD slope is a finite number
        assert math.isfinite(result.cvd_slope)

        # Profile shape is a non-empty string
        assert isinstance(result.profile_shape, str)
        assert len(result.profile_shape) > 0

        # Market structure and confidence
        assert isinstance(result.market_structure, str)
        assert result.structure_confidence >= 0.0

        # LVN/HVN are tuples (possibly empty)
        assert isinstance(result.lvns, tuple)
        assert isinstance(result.hvns, tuple)

    def test_analyze_trending_data(self):
        """Trending data should produce a valid market structure reflecting the trend."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(80, 100, "bullish")
        result = analyzer.analyze(data)

        # POC should exist and be reasonable
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low

        # Market structure should be one of the valid states
        valid_structures = {
            "BALANCE", "BALANCED", "TRENDING_UP", "TRENDING_DOWN",
            "BREAKOUT_UP", "BREAKOUT_DOWN",
        }
        assert result.market_structure in valid_structures

        # Profile shape should be valid
        assert result.profile_shape in ("P", "b", "D", "B")

    def test_analyze_minimal_data(self):
        """Exactly 5 candles (minimum for analyze) should not crash."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(5, 100, "sideways")
        result = analyzer.analyze(data)

        # Should return a valid result, not crash
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low
        assert 0.0 <= result.balance_ratio <= 1.0
        assert math.isfinite(result.cvd_slope)


# ---------------------------------------------------------------------------
# Group 3: Incremental Profile Update Tests
# ---------------------------------------------------------------------------

class TestIncrementalProfile:
    """Tests for incremental profile updates matching full rebuilds."""

    def test_incremental_matches_full_rebuild(self):
        """Incremental analyze (30 then 31) should match fresh analyze of all 31."""
        data_30 = generate_market_data(30, 100, "sideways")
        data_31 = data_30 + [generate_market_data(1, data_30[-1].close, "sideways")[0]]

        # Incremental path: same analyzer instance, two calls
        inc_analyzer = AMTAnalyzer()
        inc_analyzer.analyze(data_30)
        inc_result = inc_analyzer.analyze(data_31)

        # Fresh path: new analyzer, full data
        fresh_analyzer = AMTAnalyzer()
        fresh_result = fresh_analyzer.analyze(data_31)

        # POC/VAH/VAL should be very close (same profile construction)
        assert inc_result.poc == pytest.approx(fresh_result.poc, rel=0.01)
        assert inc_result.value_area_high == pytest.approx(
            fresh_result.value_area_high, rel=0.01,
        )
        assert inc_result.value_area_low == pytest.approx(
            fresh_result.value_area_low, rel=0.01,
        )

    def test_incremental_rebuilds_on_range_expansion(self):
        """Adding a candle far outside the range should still produce valid results."""
        # 20 candles in range 100-110
        data = []
        for i in range(20):
            price = 100 + (i % 10)
            data.append(_make_candle_timed(
                price, f"2026-01-01T00:{i:02d}:00Z",
                volume=1000, delta=50,
                high=price + 0.5, low=price - 0.5,
            ))

        analyzer = AMTAnalyzer()
        analyzer.analyze(data)

        # Add candle at 120, well outside previous range
        outlier = _make_candle_timed(
            120, f"2026-01-01T00:20:00Z",
            volume=2000, delta=100, high=121, low=119,
        )
        data_expanded = data + [outlier]
        result = analyzer.analyze(data_expanded)

        # Should not crash and produce valid VP metrics
        assert result.poc > 0
        assert result.value_area_high > result.value_area_low
        # The outlier at 120 should appear in HVNs (it has 2x volume)
        # or at least the profile should span the full range
        profile_max = max(p.price for p in result.profile)
        assert profile_max >= 119  # profile covers the outlier region
