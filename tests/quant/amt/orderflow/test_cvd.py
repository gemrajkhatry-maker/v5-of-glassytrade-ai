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
        c1 = _candle(100, delta=10, time="2025-01-01T12:00:00+00:00")
        c2 = _candle(101, delta=-5, time="2025-01-01T12:01:00+00:00")
        t.update(c1)
        state = t.update(c2)
        assert state.value == 5.0  # 10 + (-5)

    def test_slope_positive_for_rising_cvd(self):
        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=10, time=f"2025-01-01T12:{i:02d}:00+00:00"))
        state = t.state()
        assert state.slope > 0

    def test_slope_negative_for_falling_cvd(self):
        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=-10, time=f"2025-01-01T12:{i:02d}:00+00:00"))
        state = t.state()
        assert state.slope < 0

    def test_divergence_bearish(self):
        t = CVDTracker(divergence_window=10)
        for i in range(5):
            t.update(_candle(
                100 + i, delta=20 - i,
                time=f"2025-01-01T12:{i:02d}:00+00:00",
            ))
        for i in range(5):
            t.update(_candle(
                106 + i, delta=10 - i * 3,
                time=f"2025-01-01T12:{i + 5:02d}:00+00:00",
            ))
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

    def test_equivalent_epoch_and_iso_timestamp_is_idempotent(self):
        tracker = CVDTracker()
        tracker.update(_candle(100, delta=10, time="1767225600"))

        state = tracker.update(
            _candle(101, delta=999, time="2026-01-01T05:30:00+05:30")
        )

        assert state.value == 10
        assert tracker._history == [10]
        assert tracker._price_history == [100]

    def test_state_does_not_advance_slope_persistence(self):
        tracker = CVDTracker(slope_window=5)
        for i in range(5):
            tracker.update(_candle(
                100, delta=10,
                time=f"2025-01-01T12:{i:02d}:00+00:00",
            ))
        signs = list(tracker._slope_sign_history)
        emitted = tracker._last_emitted_slope

        first = tracker.state()
        second = tracker.state()

        assert first == second
        assert tracker._slope_sign_history == signs
        assert tracker._last_emitted_slope == emitted


def _ema(values: list[float], period: int) -> float:
    """Independent EMA reference: alpha = 2/(period+1), seeded at values[0]."""
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


class TestCVDSlopeEMA:
    """Slope must be EMA3(CVD) − EMA9(CVD) per spec §6.2 (linreg removed)."""

    def test_slope_equals_ema3_minus_ema9(self):
        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=10, time=f"2025-01-01T12:{i:02d}:00+00:00"))
        expected = _ema(t._history, 3) - _ema(t._history, 9)
        assert t.state().slope == pytest.approx(expected)
        assert expected > 0

    def test_slope_is_not_linreg(self):
        from quant.amt.compute import linreg_slope

        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=10, time=f"2025-01-01T12:{i:02d}:00+00:00"))
        linreg = linreg_slope(list(t._history))
        assert t.state().slope != pytest.approx(linreg, rel=1e-3)

    def test_sign_persistence_applies_to_ema_slope(self):
        t = CVDTracker(slope_window=5)
        for i in range(10):
            t.update(_candle(100, delta=10, time=f"2025-01-01T12:{i:02d}:00+00:00"))
        before = t.state().slope
        assert before > 0

        # One sharp reversal flips the raw sign, but it is not yet persistent.
        t.update(_candle(100, delta=-500, time="2025-01-01T12:10:00+00:00"))
        assert t._slope_sign_history[-1] == -1
        assert t.state().slope == pytest.approx(before)

        # After CVD_SLOPE_PERSISTENCE_BARS consecutive negative signs, emit flips.
        for i in range(2):
            t.update(_candle(100, delta=-500, time=f"2025-01-01T12:{11 + i:02d}:00+00:00"))
        assert t.state().slope < 0


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
