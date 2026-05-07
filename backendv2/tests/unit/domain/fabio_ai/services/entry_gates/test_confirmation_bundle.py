"""Tests for confirmation_bundle entry gate module.

Covers check_confirmation_bundle, check_momentum_fade, compute_atr, and detect_extreme_cvd.
"""
import pytest
from datetime import datetime, time as _time
from decimal import Decimal

from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import (
    check_confirmation_bundle,
    check_momentum_fade,
    compute_atr,
    detect_extreme_cvd,
)
from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel


def _make_candle(time_str, open=100.0, high=101.0, low=99.5, close=100.5, volume=100.0, delta=0.0):
    """Helper to create OHLC candles with sensible defaults."""
    return OHLC.create(
        time=time_str, open=open, high=high, low=low, close=close,
        volume=volume, delta=delta,
    )


def _make_history(count=25, base_volume=100.0, base_delta=0.0):
    """Create a list of historical candles."""
    candles = []
    for i in range(count):
        candles.append(_make_candle(
            time_str=f"2025-01-15T10:{i:02d}:00",
            volume=base_volume,
            delta=base_delta,
        ))
    return candles


def _make_tight_order_book():
    """Create an order book with tight spread."""
    return OrderBook(
        bids=(OrderBookLevel(price=100.0, quantity=50.0),),
        asks=(OrderBookLevel(price=100.05, quantity=50.0),),
    )


def _make_wide_order_book():
    """Create an order book with wide spread."""
    return OrderBook(
        bids=(OrderBookLevel(price=100.0, quantity=50.0),),
        asks=(OrderBookLevel(price=105.0, quantity=50.0),),
    )


# ============================================================================
# check_confirmation_bundle tests
# ============================================================================


class TestCheckConfirmationBundle:
    """Tests for the three-point confirmation bundle gate."""

    def test_volume_impulse_delta_pressure_tight_spread_passes(self):
        """3/3 signals: volume impulse + delta pressure + tight spread => pass."""
        history = _make_history(count=25, base_volume=100.0)
        # Tick with high volume (well above EMA), large delta, tight spread
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=500.0,  # >> EMA ~100 * 1.5
            delta=100.0,   # abs(100)/500 = 0.20 > 0.15
        )
        ob = _make_tight_order_book()
        assert check_confirmation_bundle(history, tick, ob) is True

    def test_volume_impulse_delta_pressure_no_order_book_passes(self):
        """2/3 signals: volume impulse + delta pressure, no order book => pass."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=500.0,
            delta=100.0,
        )
        # No order book provided — spread_tight defaults to True
        assert check_confirmation_bundle(history, tick, order_book=None) is True

    def test_volume_impulse_only_fails(self):
        """1/3 signals: volume impulse only (no delta pressure) => fail."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=500.0,
            delta=10.0,  # abs(10)/500 = 0.02 < 0.15
        )
        ob = _make_wide_order_book()  # wide spread => spread_tight=False
        assert check_confirmation_bundle(history, tick, ob) is False

    def test_no_volume_impulse_fails(self):
        """No volume impulse => fail immediately."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=50.0,  # below EMA * multiplier
            delta=100.0,
        )
        ob = _make_tight_order_book()
        assert check_confirmation_bundle(history, tick, ob) is False

    def test_insufficient_data_fails(self):
        """Fewer than 20 candles => fail."""
        history = _make_history(count=10)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=500.0, delta=100.0,
        )
        assert check_confirmation_bundle(history, tick) is False

    def test_empty_data_fails(self):
        """Empty data list => fail."""
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=500.0, delta=100.0,
        )
        assert check_confirmation_bundle([], tick) is False

    def test_mcx_lull_time_uses_lower_multiplier(self):
        """MCX lull time (13:00-17:00) uses multiplier 1.0 instead of 1.5."""
        history = _make_history(count=25, base_volume=100.0)
        # During lull time, multiplier=1.0, so volume=120 should pass impulse
        tick = OHLC.create(
            time="2025-01-15T14:30:00+05:30",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=120.0,  # > EMA*1.0 (~100) but < EMA*1.5
            delta=100.0,
        )
        ob = _make_tight_order_book()
        assert check_confirmation_bundle(history, tick, ob) is True

    def test_zero_tick_volume_fails(self):
        """Zero tick volume => fail."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=0.0,
            delta=100.0,
        )
        assert check_confirmation_bundle(history, tick) is False

    def test_delta_pressure_calculation(self):
        """Delta pressure: abs(delta)/volume > 0.15 => True."""
        history = _make_history(count=25, base_volume=100.0)
        # With tight spread, vol_impulse=True + spread_tight=True => 2/3 passes
        # regardless of delta_pressure. Use wide spread to isolate delta check.
        ob = _make_wide_order_book()  # spread_tight=False

        # volume=300 >> EMA, delta=20 => ratio=0.067 < 0.15 => delta_pressure=False
        # score = vol_impulse(1) + delta_pressure(0) + spread_tight(0) = 1/3 => fail
        tick_low_pressure = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=300.0,
            delta=20.0,
        )
        assert check_confirmation_bundle(history, tick_low_pressure, ob) is False

        # Now with delta that gives ratio > 0.15: 60/300 = 0.20
        # score = vol_impulse(1) + delta_pressure(1) + spread_tight(0) = 2/3 => pass
        tick_high_pressure = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=300.0,
            delta=60.0,
        )
        assert check_confirmation_bundle(history, tick_high_pressure, ob) is True

    def test_negative_delta_pressure(self):
        """Negative delta also counts for delta pressure (abs value)."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=300.0,
            delta=-80.0,  # abs(-80)/300 = 0.267 > 0.15
        )
        ob = _make_tight_order_book()
        assert check_confirmation_bundle(history, tick, ob) is True


# ============================================================================
# check_momentum_fade tests
# ============================================================================


class TestCheckMomentumFade:
    """Tests for momentum fade detection."""

    def test_short_fade_detected(self):
        """SHORT fade: close > open + large body + small upper wick => True."""
        history = _make_history(count=25, base_volume=100.0)
        # High volume candle with strong upward momentum
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=100.0, close=100.9,
            volume=500.0,  # >> EMA*2.5
            delta=0.0,
        )
        # body = 0.9, range = 1.0, body/range = 0.9 > 0.70
        # upper_wick = 101.0 - 100.9 = 0.1, 0.1 < 0.9*0.30 = 0.27 => True
        assert check_momentum_fade(history, tick, "SHORT") is True

    def test_long_fade_detected(self):
        """LONG fade: close < open + large body + small lower wick => True."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=100.0, low=99.0, close=99.1,
            volume=500.0,
            delta=0.0,
        )
        # body = 0.9, range = 1.0, body/range = 0.9 > 0.70
        # lower_wick = 99.1 - 99.0 = 0.1, 0.1 < 0.9*0.30 = 0.27 => True
        assert check_momentum_fade(history, tick, "LONG") is True

    def test_no_fade_volume_below_threshold(self):
        """Volume below EMA*2.5 threshold => False."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=100.0, close=100.9,
            volume=100.0,  # not > EMA*2.5 (~250)
            delta=0.0,
        )
        assert check_momentum_fade(history, tick, "SHORT") is False

    def test_insufficient_data_returns_false(self):
        """Fewer than 20 candles => False."""
        history = _make_history(count=10)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=100.0, close=100.9,
            volume=500.0, delta=0.0,
        )
        assert check_momentum_fade(history, tick, "SHORT") is False

    def test_empty_data_returns_false(self):
        """Empty data => False."""
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=100.0, close=100.9,
            volume=500.0, delta=0.0,
        )
        assert check_momentum_fade([], tick, "SHORT") is False

    def test_small_body_no_fade(self):
        """Small body (body < 70% of range) => False."""
        history = _make_history(count=25, base_volume=100.0)
        # Doji-like candle: small body relative to range
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=99.0, close=100.1,
            volume=500.0,
            delta=0.0,
        )
        # body = 0.1, range = 2.0, body/range = 0.05 < 0.70 => False
        assert check_momentum_fade(history, tick, "SHORT") is False

    def test_zero_volume_returns_false(self):
        """Zero tick volume => False."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=101.0, low=100.0, close=100.9,
            volume=0.0, delta=0.0,
        )
        assert check_momentum_fade(history, tick, "SHORT") is False

    def test_wrong_direction_no_fade(self):
        """SHORT check on a down candle => False."""
        history = _make_history(count=25, base_volume=100.0)
        tick = OHLC.create(
            time="2025-01-15T10:30:00",
            open=100.0, high=100.0, low=99.0, close=99.1,
            volume=500.0, delta=0.0,
        )
        # close < open, so SHORT condition (close > open) fails
        assert check_momentum_fade(history, tick, "SHORT") is False


# ============================================================================
# compute_atr tests
# ============================================================================


class TestComputeAtr:
    """Tests for ATR computation."""

    def test_normal_case_with_enough_data(self):
        """ATR with >= period candles returns positive value."""
        candles = []
        for i in range(20):
            candles.append(OHLC.create(
                time=f"2025-01-15T10:{i:02d}:00",
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.5 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=100.0,
            ))
        atr = compute_atr(candles, period=14)
        assert atr > 0.0
        # Each candle: high-low=1.5, so ATR should be around 1.5
        assert 1.0 < atr < 2.0

    def test_insufficient_data_returns_zero(self):
        """Fewer than 2 candles => 0.0."""
        single = [OHLC.create(
            time="2025-01-15T10:00:00",
            open=100.0, high=101.0, low=99.5, close=100.5,
            volume=100.0,
        )]
        assert compute_atr(single) == 0.0

    def test_empty_data_returns_zero(self):
        """Empty list => 0.0."""
        assert compute_atr([]) == 0.0

    def test_zero_candles(self):
        """Zero candles explicitly."""
        assert compute_atr([], period=14) == 0.0

    def test_custom_period(self):
        """Custom period smaller than data length."""
        candles = []
        for i in range(30):
            candles.append(OHLC.create(
                time=f"2025-01-15T10:{i:02d}:00",
                open=100.0,
                high=102.0,
                low=98.0,
                close=100.0,
                volume=100.0,
            ))
        atr = compute_atr(candles, period=5)
        assert atr > 0.0


# ============================================================================
# detect_extreme_cvd tests
# ============================================================================


class TestDetectExtremeCvd:
    """Tests for extreme CVD slope detection."""

    def test_above_hard_block_threshold(self):
        """CVD slope >= 50.0 => True."""
        assert detect_extreme_cvd(50.0) is True
        assert detect_extreme_cvd(75.0) is True
        assert detect_extreme_cvd(100.0) is True

    def test_below_negative_threshold(self):
        """CVD slope <= -50.0 => True."""
        assert detect_extreme_cvd(-50.0) is True
        assert detect_extreme_cvd(-75.0) is True
        assert detect_extreme_cvd(-100.0) is True

    def test_normal_range_returns_false(self):
        """Normal CVD slope => False."""
        assert detect_extreme_cvd(0.0) is False
        assert detect_extreme_cvd(10.0) is False
        assert detect_extreme_cvd(-10.0) is False
        assert detect_extreme_cvd(49.9) is False
        assert detect_extreme_cvd(-49.9) is False

    def test_none_input_returns_false(self):
        """None input => False (defaults to 0.0)."""
        assert detect_extreme_cvd(None) is False
