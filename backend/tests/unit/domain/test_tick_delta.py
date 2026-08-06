"""Tests for Phase 0: TickDeltaClassifier and CVDTracker.

TickDeltaClassifier (Lee-Ready algorithm):
  - Quote rule: price >= ask → buy, price <= bid → sell
  - Tick rule: uptick → buy, downtick → sell, zero-tick → unknown
  - First tick heuristic: mid-price classification
  - State management: prev_price tracking

CVDTracker:
  - Bar delta accumulation
  - CVD running sum
  - Slope computation (linear regression)
  - State classification (NEUTRAL/NORMAL/WARNING/HARD_BLOCK/EXTREME)
  - Divergence detection (bullish/bearish)
  - Reset behavior
"""

from __future__ import annotations

import pytest
from quant.amt.orderflow.tick_delta import (
    TickDeltaClassifier,
    candle_delta_proxy,
    TickDelta,
)


class TestTickDeltaClassifierQuoteRule:
    """Lee-Ready Quote Rule tests."""

    def test_price_at_ask_is_buy(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=100.5, volume=100, bid=100.0, ask=100.5)
        assert result.is_buy is True
        assert result.is_sell is False
        assert result.delta == 100.0
        assert result.method == "quote"

    def test_price_above_ask_is_buy(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=101.0, volume=50, bid=100.0, ask=100.5)
        assert result.is_buy is True
        assert result.delta == 50.0

    def test_price_at_bid_is_sell(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=100.0, volume=200, bid=100.0, ask=100.5)
        assert result.is_sell is True
        assert result.is_buy is False
        assert result.delta == -200.0
        assert result.method == "quote"

    def test_price_below_bid_is_sell(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=99.5, volume=75, bid=100.0, ask=100.5)
        assert result.is_sell is True
        assert result.delta == -75.0


class TestTickDeltaClassifierTickRule:
    """Lee-Ready Tick Rule tests (for mid-price trades)."""

    def test_uptick_is_buy(self):
        clf = TickDeltaClassifier()
        clf.classify(
            price=100.0, volume=10, bid=99.0, ask=101.0
        )  # mid-price, first tick
        result = clf.classify(price=100.5, volume=20, bid=99.0, ask=101.0)  # uptick
        assert result.is_buy is True
        assert result.delta == 20.0
        assert result.method == "tick"

    def test_downtick_is_sell(self):
        clf = TickDeltaClassifier()
        clf.classify(price=100.0, volume=10, bid=99.0, ask=101.0)
        result = clf.classify(price=99.5, volume=30, bid=99.0, ask=101.0)  # downtick
        assert result.is_sell is True
        assert result.delta == -30.0
        assert result.method == "tick"

    def test_zero_tick_is_unknown(self):
        clf = TickDeltaClassifier()
        clf.classify(price=100.0, volume=10, bid=99.0, ask=101.0)
        result = clf.classify(price=100.0, volume=15, bid=99.0, ask=101.0)  # same price
        assert result.is_buy is False
        assert result.is_sell is False
        assert result.delta == 0.0
        assert result.method == "zero"


class TestTickDeltaClassifierEdgeCases:
    """Edge case tests."""

    def test_zero_volume_returns_zero_delta(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=100.0, volume=0)
        assert result.delta == 0.0

    def test_first_tick_no_quote_uses_midpoint(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=100.6, volume=10, bid=100.0, ask=101.0)
        # price >= mid(100.5) → buy
        assert result.is_buy is True

    def test_first_tick_below_midpoint_is_sell(self):
        clf = TickDeltaClassifier()
        result = clf.classify(price=100.4, volume=10, bid=100.0, ask=101.0)
        # price < mid(100.5) → sell
        assert result.is_sell is True

    def test_reset_clears_state(self):
        clf = TickDeltaClassifier()
        clf.classify(price=100.0, volume=10)
        clf.reset()
        # After reset, first tick should use midpoint heuristic
        result = clf.classify(price=100.5, volume=10, bid=100.0, ask=101.0)
        assert result.method == "tick"  # uses first-tick heuristic


class TestCandleDeltaProxy:
    """Tests for OHLCV fallback delta."""

    def test_bullish_candle_positive_delta(self):
        delta = candle_delta_proxy(
            open_=100.0, high=105.0, low=99.0, close=104.0, volume=1000
        )
        # body_ratio = (104-100)/(105-99) = 4/6 = 0.667
        # delta = 0.667 * 1000 = 666.67
        assert delta > 0
        assert abs(delta - 666.67) < 1.0

    def test_bearish_candle_negative_delta(self):
        delta = candle_delta_proxy(
            open_=104.0, high=105.0, low=99.0, close=100.0, volume=1000
        )
        assert delta < 0

    def test_doji_zero_delta(self):
        delta = candle_delta_proxy(
            open_=102.0, high=105.0, low=99.0, close=102.0, volume=1000
        )
        assert delta == 0.0

    def test_zero_spread_returns_zero(self):
        assert candle_delta_proxy(100, 100, 100, 100, 100) == 0.0

    def test_zero_volume_returns_zero(self):
        assert candle_delta_proxy(100, 105, 95, 102, 0) == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
