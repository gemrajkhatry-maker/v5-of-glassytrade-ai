"""Tests for session boundary resets in CVD tracker and VWAP accumulator."""

from __future__ import annotations

import pytest
from quant.contracts.value_objects import OHLC
from quant.amt.orderflow.cvd import CVDTracker
from quant.amt.analyzer import AMTAnalyzer
from tests.helpers.market_data import generate_market_data


def _candle(close: float, time: str, delta: float = 10.0,
            volume: float = 1000.0) -> OHLC:
    h = close * 1.002
    l = close * 0.998
    return OHLC(
        time=time, open=close, high=h, low=l,
        close=close, volume=volume,
        vwap=(h + l + close) / 3,
        taker_buy_volume=(volume + delta) / 2,
        delta=delta,
    )


class TestCVDSessionReset:
    """CVD tracker should reset when time goes backwards (new session)."""

    def test_cvd_accumulates_within_session(self):
        """CVD should equal the sum of all deltas within a session."""
        tracker = CVDTracker()
        deltas = [10, -5, 20, -3, 15, 8, -12, 7, 4, -2]
        for i, d in enumerate(deltas):
            tracker.update(_candle(100, f"2026-01-01T00:{i:02d}:00Z", delta=d))

        assert tracker.value == pytest.approx(sum(deltas))

    def test_cvd_resets_on_time_reversal(self):
        """Feeding a candle with an earlier time should reset CVD."""
        tracker = CVDTracker()
        # Build up CVD over ascending timestamps
        for i in range(5):
            tracker.update(_candle(100, f"2026-01-01T00:{i:02d}:00Z", delta=20))

        assert tracker.value == pytest.approx(100)  # 5 * 20

        # New session: time goes backwards
        new_delta = 7.0
        tracker.update(_candle(100, "2026-01-01T00:00:00Z", delta=new_delta))

        # CVD should have been reset, so it equals just the new candle's delta
        assert tracker.value == pytest.approx(new_delta)

    def test_cvd_slope_resets_with_session(self):
        """After a session reset, slope should reflect only the new session data."""
        tracker = CVDTracker()
        # Old session with many candles
        for i in range(20):
            tracker.update(_candle(100, f"2026-01-01T00:{i:02d}:00Z", delta=50))

        old_state = tracker.state()
        assert old_state.value == pytest.approx(20 * 50)

        # New session: reset
        tracker.update(_candle(100, "2026-01-01T00:00:00Z", delta=1))

        new_state = tracker.state()
        # With only 1 data point after reset, slope should be 0
        assert new_state.slope == pytest.approx(0.0)


class TestVWAPSessionReset:
    """VWAP accumulator inside AMTAnalyzer should reset on session boundary."""

    def test_vwap_resets_on_new_session(self):
        """VWAP accumulator should reset when analyze() sees a time reversal.

        analyze() updates the VWAP accumulator with data[-1] on each call.
        When data[-1].time < the previous call's data[-1].time, it resets.
        """
        analyzer = AMTAnalyzer()

        # Build base data (need >= 5 candles for analyze to work)
        base = [_candle(100, f"2026-01-01T00:{i:02d}:00Z") for i in range(10)]

        # Session 1: feed candles with ascending times, prices ~ 100
        for i in range(10, 30):
            candle = _candle(100 + (i % 3) * 0.2, f"2026-01-01T00:{i:02d}:00Z")
            base.append(candle)
            analyzer.analyze(base)

        result1 = analyzer.analyze(base)
        vwap1 = result1.session_vwap
        assert vwap1 == pytest.approx(100, abs=3)

        # Session 2: time goes backwards, prices ~ 200
        # The last candle in base was at 00:29. New data ends at 00:05, which
        # is earlier, triggering a VWAP reset.
        session2_base = [_candle(200, f"2026-01-01T00:{i:02d}:00Z") for i in range(6)]
        result2 = analyzer.analyze(session2_base)
        vwap2 = result2.session_vwap

        # After reset, VWAP should reflect only the ~200 price candle
        assert vwap2 == pytest.approx(200, abs=3)
