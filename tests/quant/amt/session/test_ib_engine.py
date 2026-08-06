"""Tests for InitialBalanceEngine — ported from backend/tests/unit/domain/test_ib_and_short.py.

Only the TestInitialBalanceEngine class is ported; TestShortGates covers
short_signal_gates (out of scope for Track A4).
"""

from __future__ import annotations

from app.domain.services.initial_balance_engine import (
    InitialBalanceEngine as LegacyInitialBalanceEngine,
)
from quant.amt.session.ib_engine import IBLocation, IBState, InitialBalanceEngine
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _make_candle(time: str, o: float, h: float, l: float, c: float) -> OHLC:
    return OHLC.create(time=time, open=o, high=h, low=l, close=c, volume=100)


class TestInitialBalanceEngine:
    def test_initial_state_not_complete(self):
        engine = InitialBalanceEngine(ib_minutes=30)
        assert not engine.is_complete

    def test_ib_tracks_high_low(self):
        engine = InitialBalanceEngine(ib_minutes=30)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.update(_make_candle("2024-01-01T09:20:00", 102, 110, 98, 108))
        assert engine.ib_high == 110.0
        assert engine.ib_low == 95.0

    def test_ib_mid_and_width(self):
        engine = InitialBalanceEngine(ib_minutes=30)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.update(_make_candle("2024-01-01T09:20:00", 102, 110, 98, 108))
        assert engine.ib_mid == 102.5
        assert engine.ib_width == 15.0

    def test_ib_completes_after_window(self):
        engine = InitialBalanceEngine(ib_minutes=30)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        state = engine.update(_make_candle("2024-01-01T09:45:00", 102, 108, 100, 105))
        assert state.is_complete is True

    def test_ib_does_not_update_after_complete(self):
        engine = InitialBalanceEngine(ib_minutes=10)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.update(_make_candle("2024-01-01T09:20:00", 102, 108, 100, 105))
        state = engine.update(_make_candle("2024-01-01T09:26:00", 105, 120, 90, 115))
        assert state.is_complete
        assert engine.ib_high == 120.0
        assert engine.ib_low == 90.0
        engine.update(_make_candle("2024-01-01T09:30:00", 110, 130, 80, 125))
        assert engine.ib_high == 120.0
        assert engine.ib_low == 90.0

    def test_location_above_ib(self):
        engine = InitialBalanceEngine(ib_minutes=10)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.update(_make_candle("2024-01-01T09:25:00", 102, 108, 100, 105))
        state = engine.update(_make_candle("2024-01-01T09:30:00", 110, 115, 108, 112))
        assert state.location == IBLocation.ABOVE

    def test_location_below_ib(self):
        engine = InitialBalanceEngine(ib_minutes=10)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.update(_make_candle("2024-01-01T09:25:00", 102, 108, 100, 105))
        state = engine.update(_make_candle("2024-01-01T09:30:00", 90, 92, 88, 89))
        assert state.location == IBLocation.BELOW

    def test_classify_breakout(self):
        engine = InitialBalanceEngine(ib_minutes=10)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.update(_make_candle("2024-01-01T09:25:00", 102, 108, 100, 105))
        assert (
            engine.classify_breakout(
                _make_candle("2024-01-01T09:30:00", 105, 112, 104, 110)
            )
            == "LONG_BREAKOUT"
        )

    def test_reset(self):
        engine = InitialBalanceEngine(ib_minutes=30)
        engine.update(_make_candle("2024-01-01T09:15:00", 100, 105, 95, 102))
        engine.reset()
        assert engine.ib_high == 0.0
        assert not engine.is_complete


# ======================================================================
# Parity: legacy shim vs quant module on a fixed 30-candle series
# ======================================================================


def _series():
    candles = []
    for i in range(30):
        time = f"2026-01-01T09:{i:02d}:00"
        base = 100 + i * 0.5
        candles.append(_make_candle(time, base, base + 4, base - 3, base + 1))
    return candles


def test_initial_balance_engine_parity():
    legacy = LegacyInitialBalanceEngine(ib_minutes=30)
    new = InitialBalanceEngine(ib_minutes=30)
    states_l, states_n = [], []
    for c in _series():
        states_l.append(legacy.update(c))
        states_n.append(new.update(c))
    for l, n in zip(states_l, states_n):
        assert_parity(lambda: l, lambda: n)

    assert_parity(lambda: legacy.ib_high, lambda: new.ib_high)
    assert_parity(lambda: legacy.ib_low, lambda: new.ib_low)
    assert_parity(lambda: legacy.ib_mid, lambda: new.ib_mid)
    assert_parity(lambda: legacy.ib_width, lambda: new.ib_width)
    assert_parity(lambda: legacy.is_complete, lambda: new.is_complete)
    assert_parity(
        lambda: legacy.classify_breakout(_series()[29]),
        lambda: new.classify_breakout(_series()[29]),
    )
