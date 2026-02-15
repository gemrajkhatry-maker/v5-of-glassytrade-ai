"""Unit tests for AMT analyzer domain service."""

from __future__ import annotations

import pytest
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
from app.domain.fabio_ai.services.amt_analyzer import (
    smooth_array, create_profile, find_lvns, find_hvns,
    find_aggressive_prints, AMTAnalyzer,
)
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
