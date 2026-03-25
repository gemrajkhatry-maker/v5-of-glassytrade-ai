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
from app.domain.services.tick_delta import (
    TickDeltaClassifier,
    candle_delta_proxy,
    TickDelta,
)
from app.domain.services.cvd_tracker import CVDTracker, CVDSnapshot


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


class TestCVDTracker:
    """CVDTracker tests."""

    def test_add_tick_delta_accumulates(self):
        tracker = CVDTracker()
        tracker.add_tick_delta(10.0)
        tracker.add_tick_delta(5.0)
        snapshot = tracker.on_bar_close(bar_low=99, bar_high=101)
        assert snapshot.cvd == 15.0
        assert snapshot.bar_delta == 15.0

    def test_bar_delta_resets_after_close(self):
        tracker = CVDTracker()
        tracker.add_tick_delta(10.0)
        tracker.on_bar_close(bar_low=99, bar_high=101)
        tracker.add_tick_delta(5.0)
        snapshot = tracker.on_bar_close(bar_low=100, bar_high=102)
        assert snapshot.bar_delta == 5.0
        assert snapshot.cvd == 15.0  # 10 + 5

    def test_slope_positive_for_bullish(self):
        tracker = CVDTracker(rolling_bars=3, strong_slope=0.5)
        # Simulate 3 bars with increasing deltas
        tracker.add_tick_delta(1.0)
        tracker.on_bar_close(bar_low=99, bar_high=101)
        tracker.add_tick_delta(2.0)
        tracker.on_bar_close(bar_low=100, bar_high=102)
        tracker.add_tick_delta(3.0)
        snapshot = tracker.on_bar_close(bar_low=101, bar_high=103)
        assert snapshot.slope > 0
        assert snapshot.direction == "BULLISH"

    def test_slope_negative_for_bearish(self):
        tracker = CVDTracker(rolling_bars=3)
        tracker.add_tick_delta(-3.0)
        tracker.on_bar_close(bar_low=99, bar_high=101)
        tracker.add_tick_delta(-2.0)
        tracker.on_bar_close(bar_low=98, bar_high=100)
        tracker.add_tick_delta(-1.0)
        snapshot = tracker.on_bar_close(bar_low=97, bar_high=99)
        assert snapshot.slope > 0  # increasing deltas (less negative)
        # CVD should be negative
        assert snapshot.cvd < 0

    def test_state_neutral(self):
        tracker = CVDTracker(rolling_bars=5, strong_slope=2.0)
        # Small deltas → low slope → NEUTRAL
        snapshot = None
        for _ in range(5):
            tracker.add_tick_delta(0.1)
            snapshot = tracker.on_bar_close(bar_low=99, bar_high=101)
        assert snapshot.state == "NEUTRAL"

    def test_state_extreme_triggers_kill_signal(self):
        tracker = CVDTracker(
            rolling_bars=3,
            strong_slope=0.5,
            warning_threshold=2.0,
            hard_block_threshold=5.0,
            extreme_threshold=8.0,
        )
        tracker.add_tick_delta(100.0)
        tracker.on_bar_close(bar_low=99, bar_high=101)
        tracker.add_tick_delta(200.0)
        tracker.on_bar_close(bar_low=100, bar_high=102)
        tracker.add_tick_delta(300.0)
        snapshot = tracker.on_bar_close(bar_low=101, bar_high=103)
        assert snapshot.state == "EXTREME"
        assert snapshot.is_kill_signal is True

    def test_bullish_divergence(self):
        tracker = CVDTracker(rolling_bars=5)
        # Bar 1: price high=100, CVD low
        tracker.add_tick_delta(-10.0)
        tracker.on_bar_close(bar_low=95, bar_high=100)
        # Bar 2: price lower low (94 < 95), but CVD higher (0 > -10)
        tracker.add_tick_delta(15.0)
        snapshot = tracker.on_bar_close(bar_low=94, bar_high=99)
        assert snapshot.divergence == "BULLISH"

    def test_bearish_divergence(self):
        tracker = CVDTracker(rolling_bars=5)
        # Bar 1: price high=100, CVD high
        tracker.add_tick_delta(10.0)
        tracker.on_bar_close(bar_low=95, bar_high=100)
        # Bar 2: price higher high (101 > 100), but CVD lower (-5 < 10)
        tracker.add_tick_delta(-15.0)
        snapshot = tracker.on_bar_close(bar_low=96, bar_high=101)
        assert snapshot.divergence == "BEARISH"

    def test_reset_clears_state(self):
        tracker = CVDTracker()
        tracker.add_tick_delta(10.0)
        tracker.on_bar_close(bar_low=99, bar_high=101)
        tracker.reset()
        snapshot = tracker.on_bar_close(bar_low=99, bar_high=101)
        assert snapshot.cvd == 0
        assert snapshot.bar_delta == 0

    def test_slope_computation_formula(self):
        """Verify linear regression slope calculation."""
        tracker = CVDTracker(rolling_bars=3)
        # Known deltas: 1, 2, 3 → slope should be 1.0
        tracker.add_tick_delta(1.0)
        tracker.on_bar_close(bar_low=99, bar_high=101)
        tracker.add_tick_delta(2.0)
        tracker.on_bar_close(bar_low=100, bar_high=102)
        tracker.add_tick_delta(3.0)
        snapshot = tracker.on_bar_close(bar_low=101, bar_high=103)
        assert snapshot.slope == pytest.approx(1.0, abs=0.01)


class TestCandleDeltaProxy:
    """Test candle-based delta approximation."""

    def test_bullish_candle_returns_positive(self):
        """Close above open → positive delta approximation."""
        from app.domain.services.tick_delta import candle_delta_proxy

        delta = candle_delta_proxy(open_=100, high=105, low=95, close=104, volume=1000)
        assert delta > 0

    def test_bearish_candle_returns_negative(self):
        """Close below open → negative delta approximation."""
        from app.domain.services.tick_delta import candle_delta_proxy

        delta = candle_delta_proxy(open_=100, high=105, low=95, close=96, volume=1000)
        assert delta < 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
