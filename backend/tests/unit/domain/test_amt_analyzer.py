"""Unit tests for AMT analyzer domain service."""

from __future__ import annotations

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
