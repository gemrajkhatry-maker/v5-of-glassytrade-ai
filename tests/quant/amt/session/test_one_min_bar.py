"""Tests for OneMinBarEngine — standalone unit + parity.

No dedicated backend test existed for one_min_bar_engine (grep found zero hits);
unit tests mirror the established port style, parity drives a fixed tick stream
through both implementations via assert_parity.
"""

from __future__ import annotations

from app.domain.services.one_min_bar_engine import (
    OneMinBarEngine as LegacyOneMinBarEngine,
)
from quant.amt.session.one_min_bar import OneMinBarEngine, OneMinBarState
from tests.quant.parity import assert_parity


def _ticks():
    """Fixed tick stream spanning several 1-min bars."""
    ticks = []
    for i in range(40):
        minute = 9 + i // 10
        sec = (i % 10) * 6
        ts = f"2026-01-01T{minute:02d}:00:{sec:02d}"
        price = 100.0 + i * 0.25
        ticks.append(
            (ts, price, 10.0 + (i % 3), 5.0 if i % 2 == 0 else -5.0)
        )
    return ticks


class TestOneMinBarEngine:
    def test_initial_state_empty(self):
        engine = OneMinBarEngine()
        assert engine._bar_states == {}

    def test_first_tick_starts_bar(self):
        engine = OneMinBarEngine()
        state = engine.update("NIFTY", 100.0, 10.0, 5.0, "2026-01-01T09:00:00")
        assert state.is_new_bar is True
        assert state.close == 100.0
        assert state.volume == 10.0
        assert state.bar_time == "2026-01-01T09:00:00"

    def test_tick_accumulates_volume(self):
        engine = OneMinBarEngine()
        engine.update("NIFTY", 100.0, 10.0, 5.0, "2026-01-01T09:00:10")
        state = engine.update("NIFTY", 100.5, 15.0, 10.0, "2026-01-01T09:00:30")
        assert state.volume == 25.0
        assert state.close == 100.5
        assert state.is_new_bar is False

    def test_new_bar_finalizes_previous(self):
        engine = OneMinBarEngine()
        engine.update("NIFTY", 100.0, 10.0, 5.0, "2026-01-01T09:00:10")
        state = engine.update("NIFTY", 101.0, 10.0, 8.0, "2026-01-01T09:01:00")
        assert state.is_new_bar is True
        assert state.close == 101.0

    def test_cvd_slope_over_bars(self):
        engine = OneMinBarEngine()
        # Accumulate 3 bars of pure-buy delta
        for i in range(3):
            ts = f"2026-01-01T09:0{i}:00"
            engine.update("NIFTY", 100.0 + i, 10.0, 10.0, ts)
        state = engine.update("NIFTY", 103.0, 10.0, 10.0, "2026-01-01T09:03:00")
        # cvd_bars has [10,10,10] → slope 0
        assert state.cvd_slope == 0.0
        assert state.volume == 10.0

    def test_aggression_positive_delta(self):
        engine = OneMinBarEngine()
        state = engine.update("NIFTY", 100.0, 100.0, 60.0, "2026-01-01T09:00:00")
        assert state.aggression >= 1.0

    def test_invalid_timestamp_uses_raw(self):
        engine = OneMinBarEngine()
        state = engine.update("NIFTY", 100.0, 10.0, 5.0, "not-a-timestamp")
        assert state.bar_time == "not-a-timestamp"


# ======================================================================
# Parity: fixed tick stream through legacy shim vs quant module
# ======================================================================


def _run(factory):
    engine = factory()
    outputs = []
    for ts, price, vol, delta in _ticks():
        outputs.append(engine.update("NIFTY", price, vol, delta, ts))
    return outputs


def test_one_min_bar_parity_tick_stream():
    legacy = _run(LegacyOneMinBarEngine)
    new = _run(OneMinBarEngine)
    for l, n in zip(legacy, new):
        assert_parity(lambda: l, lambda: n)
