"""Tests for InitialBalanceEngine."""

import pytest

from quant.amt.session.ib_engine import (
    IBLocation,
    IBState,
    InitialBalanceEngine,
)
from quant.contracts.value_objects import OHLC


# ===== Initial Balance Engine =====


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
        # IB window 10 min elapsed (09:15 to 09:25)
        state = engine.update(_make_candle("2024-01-01T09:26:00", 105, 120, 90, 115))
        assert state.is_complete
        # The last candle in the window IS included in IB high/low (update happens before completeness check)
        assert engine.ib_high == 120.0
        assert engine.ib_low == 90.0
        # Subsequent candles should NOT update IB
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
