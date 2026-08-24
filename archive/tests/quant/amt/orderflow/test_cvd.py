"""Tests for quant.amt.orderflow.cvd — ported from backend CVD tracker tests."""

import pytest

from quant.amt.orderflow.cvd import CVDTracker, CVDState
from quant.contracts.value_objects import OHLC


def _candle(close: float, volume: float = 100.0, delta: float = 0.0,
            time: str = "2025-01-01T12:00:00+00:00") -> OHLC:
    return OHLC(
        time=time,
        open=close * 0.999,
        high=close * 1.001,
        low=close * 0.998,
        close=close,
        volume=volume,
        delta=delta,
    )


class TestCVDTracker:
    def test_accumulates_delta(self):
        t = CVDTracker()
        c1 = _candle(100, delta=10)
        c2 = _candle(101, delta=-5)
        t.update(c1)
        state = t.update(c2)
        assert state.value == 5.0  # 10 + (-5)

    def test_slope_positive_for_rising_cvd(self):
        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=10))
        state = t.state()
        assert state.slope > 0

    def test_slope_negative_for_falling_cvd(self):
        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=-10))
        state = t.state()
        assert state.slope < 0

    def test_divergence_bearish(self):
        t = CVDTracker(divergence_window=10)
        for i in range(5):
            t.update(_candle(100 + i, delta=20 - i))
        for i in range(5):
            t.update(_candle(106 + i, delta=10 - i * 3))
        state = t.state()
        assert isinstance(state.divergence_type, str)
        assert state.divergence_type in ("BEARISH_DIV", "BULLISH_DIV", "NONE")

    def test_reset_clears_state(self):
        t = CVDTracker()
        t.update(_candle(100, delta=50))
        t.reset()
        assert t.value == 0.0

    def test_state_type(self):
        t = CVDTracker()
        state = t.update(_candle(100, delta=5))
        assert isinstance(state, CVDState)


class TestCVDSessionReset:
    def test_cvd_accumulates_within_session(self):
        tracker = CVDTracker()
        deltas = [10, -5, 20, -3, 15, 8, -12, 7, 4, -2]
        for i, d in enumerate(deltas):
            tracker.update(_candle(100, delta=d, time=f"2026-01-01T00:{i:02d}:00Z"))
        assert tracker.value == pytest.approx(sum(deltas))

    def test_cvd_resets_on_time_reversal(self):
        tracker = CVDTracker()
        for i in range(5):
            tracker.update(_candle(100, delta=20, time=f"2026-01-01T00:{i:02d}:00Z"))
        assert tracker.value == pytest.approx(100)
        new_delta = 7.0
        tracker.update(_candle(100, delta=new_delta, time="2026-01-01T00:00:00Z"))
        assert tracker.value == pytest.approx(new_delta)

    def test_cvd_slope_resets_with_session(self):
        tracker = CVDTracker()
        for i in range(20):
            tracker.update(_candle(100, delta=50, time=f"2026-01-01T00:{i:02d}:00Z"))
        old_state = tracker.state()
        assert old_state.value == pytest.approx(20 * 50)
        tracker.update(_candle(100, delta=1, time="2026-01-01T00:00:00Z"))
        new_state = tracker.state()
        assert new_state.slope == pytest.approx(0.0)
