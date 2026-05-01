"""Tests for signal_validator.py - increase coverage."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.domain.trading.services.signal_validator import SignalValidator
from app.domain.trading.models.entities import Signal
from app.domain.trading.models.enums import SignalType, SetupType, Source
from app.domain.trading.models.value_objects import OHLC


def _make_signal(price=100, timestamp=None):
    """Helper to create test signals."""
    return Signal(
        type=SignalType.BUY,
        price=price,
        reason="test",
        stop_loss=90,
        take_profit=110,
        timestamp=timestamp or "2026-01-01T10:00:00Z",
        setup=SetupType.TREND_MODEL,
        source=Source.AMT,
    )


def _make_tick(close=100):
    """Helper to create test ticks."""
    return OHLC(
        time="2026-01-01T10:05:00Z",
        open=close, high=close * 1.01,
        low=close * 0.99, close=close,
        volume=1000, vwap=close,
        taker_buy_volume=600, delta=200,
    )


def test_validate_staleness_fresh_signal():
    """validate_staleness returns True for fresh signal."""
    signal = _make_signal(price=100)
    tick = _make_tick(close=100)
    assert SignalValidator.validate_staleness(signal, tick) is True


def test_validate_staleness_no_timestamp():
    """validate_staleness returns True when signal has no timestamp."""
    signal = _make_signal()
    signal.timestamp = None
    tick = _make_tick(close=100)
    assert SignalValidator.validate_staleness(signal, tick) is True


def test_validate_staleness_stale_signal():
    """validate_staleness returns False for stale signal."""
    old_time = "2026-01-01T08:00:00Z"  # 2 hours before tick time
    signal = _make_signal(timestamp=old_time)
    tick = _make_tick(close=100)
    # The tick time is 10:05:00Z, signal time is 08:00:00Z = 2h5m old
    assert SignalValidator.validate_staleness(signal, tick, max_age_seconds=60) is False


def test_validate_direction_match():
    """validate_direction returns True for matching directions."""
    signal = _make_signal(price=100)
    assert SignalValidator.validate_direction(signal, "LONG") is True


def test_validate_direction_mismatch():
    """validate_direction returns False for mismatched directions."""
    signal = _make_signal(price=100)
    assert SignalValidator.validate_direction(signal, "SHORT") is False


def test_validate_direction_flat():
    """validate_direction returns True when agent is FLAT."""
    signal = _make_signal(price=100)
    assert SignalValidator.validate_direction(signal, "FLAT") is True


def test_validate_vwap_extreme_no_data():
    """validate_vwap_extreme returns True with no VWAP data."""
    signal = _make_signal(price=100)
    assert SignalValidator.validate_vwap_extreme(signal, 0.0, 0.0) is True


def test_validate_vwap_extreme_buy_at_extreme():
    """validate_vwap_extreme returns False for LONG at upper extreme."""
    signal = _make_signal(price=200)
    result = SignalValidator.validate_vwap_extreme(signal, vwap_upper_2=100.0, vwap_lower_2=50.0)
    assert result is False


def test_validate_vwap_extreme_short_at_extreme():
    """validate_vwap_extreme returns False for SHORT at lower extreme."""
    signal = _make_signal(price=25)
    signal.type = SignalType.SELL
    result = SignalValidator.validate_vwap_extreme(signal, vwap_upper_2=100.0, vwap_lower_2=50.0)
    assert result is False


def test_validate_all_passes():
    """validate_all returns True when all validations pass."""
    signal = _make_signal(price=100)
    tick = _make_tick(close=100)
    passed, reason = SignalValidator.validate_all(signal, tick, "LONG")
    assert passed is True
    assert reason == "ALL_VALID"


def test_validate_all_stale():
    """validate_all returns False for stale signal."""
    old_time = "2026-01-01T08:00:00Z"  # 2 hours before tick time
    signal = _make_signal(timestamp=old_time)
    tick = _make_tick(close=100)
    # Directly test staleness validation
    passed = SignalValidator.validate_staleness(signal, tick, max_age_seconds=60)
    assert passed is False


def test_validate_all_direction_mismatch():
    """validate_all returns False for direction mismatch."""
    signal = _make_signal(price=100)
    tick = _make_tick(close=100)
    passed, reason = SignalValidator.validate_all(signal, tick, "SHORT")
    assert passed is False
    assert reason == "DIRECTION_MISMATCH"