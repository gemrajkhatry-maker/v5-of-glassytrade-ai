"""Unit tests for ValueMigrationTracker (session VA development over 15-min windows)."""

import pytest

from quant.amt.profile.migration import (
    ValueMigrationTracker,
    classify_value_migration,
)
from quant.contracts.value_objects import OHLC

SESSION_OPEN = "2026-01-01T09:00:00Z"


def _candle(time: str, close: float = 100.0) -> OHLC:
    return OHLC(
        time=time,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
        delta=0,
    )


def test_insufficient_until_second_window_closes():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    m = t.update(_candle("2026-01-01T09:14:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    assert not m.has_migration
    assert m.direction == "INSUFFICIENT"
    assert m.poc_drift == 0.0


def test_drift_and_migrating_up_direction():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    m = t.update(_candle("2026-01-01T09:15:00Z"), 102, 107, 97, session_open=SESSION_OPEN)
    assert m.has_migration
    assert m.poc_drift == pytest.approx(2.0)
    assert m.vah_drift == pytest.approx(2.0)
    assert m.val_drift == pytest.approx(2.0)
    assert m.direction == "MIGRATING_UP"
    assert m.window_label == "09:00→09:15"


def test_expanding_direction():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    m = t.update(_candle("2026-01-01T09:15:00Z"), 100, 108, 92, session_open=SESSION_OPEN)
    assert m.direction == "EXPANDING"


def test_contracting_direction():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    m = t.update(_candle("2026-01-01T09:15:00Z"), 100, 102, 98, session_open=SESSION_OPEN)
    assert m.direction == "CONTRACTING"


def test_flat_direction_below_noise():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    m = t.update(_candle("2026-01-01T09:15:00Z"), 100.001, 105.001, 95.001, session_open=SESSION_OPEN)
    assert m.direction == "FLAT"
    assert m.has_migration


def test_latest_values_within_a_window_are_used():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    # Sub-window updates overwrite the window's sample.
    t.update(_candle("2026-01-01T09:14:00Z"), 101, 106, 96, session_open=SESSION_OPEN)
    m = t.update(_candle("2026-01-01T09:15:00Z"), 101, 106, 96, session_open=SESSION_OPEN)
    assert m.poc_drift == pytest.approx(0.0)
    assert m.vah_drift == pytest.approx(0.0)
    assert m.val_drift == pytest.approx(0.0)
    assert m.direction == "FLAT"


def test_skipped_window_compares_latest_two_samples():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    # Jump straight from window 0 to window 2 (no bars in window 1).
    m = t.update(_candle("2026-01-01T09:30:00Z"), 103, 108, 98, session_open=SESSION_OPEN)
    assert m.has_migration
    assert m.poc_drift == pytest.approx(3.0)
    assert m.window_label == "09:00→09:30"


def test_new_session_day_resets_migration():
    t = ValueMigrationTracker()
    t.update(_candle("2026-01-01T09:00:00Z"), 100, 105, 95, session_open=SESSION_OPEN)
    t.update(_candle("2026-01-01T09:15:00Z"), 102, 107, 97, session_open=SESSION_OPEN)
    m = t.update(
        _candle("2026-01-02T09:15:00Z"), 100, 105, 95,
        session_open="2026-01-02T09:00:00Z",
    )
    assert not m.has_migration
    assert m.direction == "INSUFFICIENT"


def test_classify_value_migration_edges():
    assert classify_value_migration(1.0, -1.0, 0.1) == "EXPANDING"
    assert classify_value_migration(-1.0, 1.0, 0.1) == "CONTRACTING"
    assert classify_value_migration(1.0, 1.0, 0.1) == "MIGRATING_UP"
    assert classify_value_migration(-1.0, -1.0, 0.1) == "MIGRATING_DOWN"
    assert classify_value_migration(0.0, 0.0, 0.1) == "FLAT"


def test_analyzer_exposes_value_migration_on_result():
    """The full analyze() pipeline wires the tracker: after two 15-min windows
    the AMTResult carries a live value-migration with a window label."""
    from quant.amt.analyzer import AMTAnalyzer

    analyzer = AMTAnalyzer()
    data = []
    # Window 0: 09:00-09:04 (session opens 09:00) at ~100.
    for i in range(5):
        t = f"2026-01-01T09:{i:02d}:00Z"
        data.append(_candle(t, close=100.0 + i * 0.1))
    # Window 1: 09:15-09:19 at ~102.
    for i in range(15, 20):
        t = f"2026-01-01T09:{i:02d}:00Z"
        data.append(_candle(t, close=102.0 + (i - 15) * 0.1))

    result = None
    for i in range(1, len(data) + 1):
        result = analyzer.analyze(data[:i])

    assert result is not None
    assert result.value_migration.has_migration, (
        "analyze() must surface value migration after two 15-min windows"
    )
    assert result.value_migration.window_label.startswith("09:00→09:15")
    assert result.value_migration.direction in {
        "MIGRATING_UP", "MIGRATING_DOWN", "EXPANDING", "CONTRACTING", "FLAT",
    }
