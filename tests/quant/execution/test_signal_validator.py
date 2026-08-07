"""Tests for SignalValidator."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from quant.execution.signal_validator import SignalValidator
from quant.contracts.entities import Signal
from quant.contracts.enums import SignalType, SetupType, Source


def test_signal_validator_validate_staleness_fresh():
    """validate_staleness returns True for fresh signal."""
    validator = SignalValidator()
    signal = Signal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="test",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )
    current_tick = type("Tick", (), {"close": 100.0, "time": datetime.now(timezone.utc).isoformat()})()
    assert validator.validate_staleness(signal, current_tick) is True


def test_signal_validator_validate_staleness_stale():
    """validate_staleness returns False for stale signal (default 60s TTL)."""
    validator = SignalValidator()
    # 5 minutes old — well beyond the 60s default TTL
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    signal = Signal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="test",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp=old_time,
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )
    current_tick = type("Tick", (), {"close": 100.0, "time": datetime.now(timezone.utc).isoformat()})()
    assert validator.validate_staleness(signal, current_tick) is False


def _make_validator_signal(timestamp: str) -> Signal:
    return Signal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="test",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp=timestamp,
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )


def test_signal_validator_validate_staleness_default_rejects_over_60s():
    """Default max_age_seconds (60s) rejects a signal older than 60s."""
    signal = _make_validator_signal("2026-01-01T10:00:00Z")
    current_tick = type("Tick", (), {"close": 100.0, "time": "2026-01-01T10:01:01Z"})()
    assert SignalValidator.validate_staleness(signal, current_tick) is False


def test_signal_validator_validate_staleness_default_accepts_under_60s():
    """Default max_age_seconds (60s) accepts a signal younger than 60s."""
    signal = _make_validator_signal("2026-01-01T10:00:00Z")
    current_tick = type("Tick", (), {"close": 100.0, "time": "2026-01-01T10:00:59Z"})()
    assert SignalValidator.validate_staleness(signal, current_tick) is True


def test_signal_validator_validate_staleness_overridable_longer_window():
    """Callers can still pass an explicit longer window (e.g. 600s)."""
    signal = _make_validator_signal("2026-01-01T10:00:00Z")
    current_tick = type("Tick", (), {"close": 100.0, "time": "2026-01-01T10:05:00Z"})()
    assert SignalValidator.validate_staleness(signal, current_tick) is False
    assert SignalValidator.validate_staleness(signal, current_tick, max_age_seconds=600) is True