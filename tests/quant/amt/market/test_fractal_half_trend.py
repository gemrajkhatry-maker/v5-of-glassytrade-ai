"""Tests for the ChartArt Fractal Breakout (half-trend) detector.

Faithful-port verification: each test mirrors the Pine script semantics
(fractal top = 5-bar high window, fractal_price = valuewhen(..., 1) — the
second most recent fractal top, fractal_average over the fractal_price
series' prior 2/3 bars, fractal_trend = average rising, fractal_breakout =
prior bar's price above the fractal price, entry = trend & breakout,
exit = trend flip after n_time bars).

Sequences below were verified against a bar-by-bar trace of the detector.
"""

import pytest

from quant.amt.market.fractal_half_trend import (
    FractalHalfTrendDetector,
    FractalHalfTrendResult,
)
from quant.contracts.value_objects import OHLC


def _bar(high: float, low: float, close: float, t: str = "") -> OHLC:
    return OHLC.create(time=t, open=close, high=high, low=low, close=close, volume=100)


def _feed(det: FractalHalfTrendDetector, highs: list[float]) -> FractalHalfTrendResult:
    res = None
    for i, h in enumerate(highs):
        res = det.update(_bar(h, h - 0.5, h, str(i)))
    assert res is not None
    return res


# Rising fractal tops: 11.25 (confirmed idx4), 13.25 (idx9), 15.25 (idx14).
# From idx15 the 3-fractal average rises -> trend UP; prior-bar price stays
# above the fractal price -> breakout; BUY fires on idx15/16.
_RISING = [10.0, 9.0, 12.0, 11.0, 11.5, 11.6, 11.7, 14.0, 13.0, 13.5,
           14.6, 15.0, 16.0, 15.0, 15.5, 15.8, 17.0]

# _RISING + rollover: a lower local peak confirms f4=14.25 (idx18), then
# f5 (idx23) — the fractal average falls and the trend flips down.
_RISING_THEN_ROLLOVER = _RISING + [15.0, 14.5, 15.2, 15.0, 15.4, 15.1,
                                   14.8, 15.3]


class TestFractalTopDetection:
    """Pine: fractal_top = high[2] > high[3] and high[2] > high[4]
    and high[2] > high[1] and high[2] > high[0]."""

    def test_no_fractal_before_five_bars(self):
        det = FractalHalfTrendDetector()
        for h in (10.0, 11.0, 12.0):
            res = det.update(_bar(h, h * 0.99, h))
            assert res.fractal_top is False

    def test_fractal_top_confirmed_two_bars_after_peak(self):
        det = FractalHalfTrendDetector()
        # bars 0..4: peak at index 2; confirmation arrives when bar index 4
        # closes (both right neighbours are lower).
        results = [det.update(_bar(h, h - 0.5, h, str(i)))
                   for i, h in enumerate([10.0, 9.0, 12.0, 11.0, 11.5])]
        assert not any(r.fractal_top for r in results[:4])
        assert results[4].fractal_top is True
        # Pine valuewhen(..., 1) exposes the fractal only once a SECOND one
        # exists — until then the series is na (0.0 here), on the next bar too.
        nxt = det.update(_bar(11.6, 11.1, 11.6, "5"))
        assert nxt.last_fractal_price == 0.0

    def test_higher_high_right_neighbour_suppresses_fractal(self):
        det = FractalHalfTrendDetector()
        # 10, 9, 12, 13 -> peak candidate 12 is not > 13 on the right
        res = _feed(det, [10.0, 9.0, 12.0, 13.0, 12.5])
        assert res.fractal_top is False


class TestFractalAverageAndTrend:
    """Pine: fractal_average over the fractal_price series' prior 2/3 bars;
    fractal_trend = fractal_average[0] > fractal_average[1]."""

    def test_average_is_zero_until_enough_fractals(self):
        det = FractalHalfTrendDetector()
        # Only one fractal forms in this sequence
        res = _feed(det, [10.0, 9.0, 12.0, 11.0, 11.5, 11.0, 10.5])
        assert res.fractal_average == 0.0
        assert res.fractal_trend is False

    def test_trend_true_when_average_rising(self):
        det = FractalHalfTrendDetector()
        res = _feed(det, _RISING)
        # fractal tops 11.25 -> 13.25 -> 15.25 (third confirms on the last
        # bar, so the fps series still reads 13.25); the average rises
        assert res.last_fractal_price == pytest.approx(13.25)
        assert res.fractal_average == pytest.approx((11.25 + 13.25 + 13.25) / 3)
        assert res.fractal_trend is True

    def test_trend_false_when_average_falling(self):
        det = FractalHalfTrendDetector()
        res = _feed(det, _RISING_THEN_ROLLOVER)
        # After the rollover the fractal average is falling
        assert res.fractal_average > 0.0
        assert res.fractal_trend is False


class TestFractalBreakout:
    """Pine (no-repainting): fractal_breakout = price[1] > fractal_price[0]."""

    def test_breakout_when_prior_bar_price_above_fractal_price(self):
        det = FractalHalfTrendDetector()
        # Second fractal (13.25) confirms at idx9; from then on the
        # fractal price (11.25) is live and the prior bar sits above it.
        res = _feed(det, [10.0, 9.0, 12.0, 11.0, 11.5, 11.6, 11.7, 14.0, 13.0, 13.5])
        assert res.fractal_breakout is True
        assert res.last_fractal_price == pytest.approx(11.25)

    def test_no_breakout_before_two_fractals(self):
        det = FractalHalfTrendDetector()
        # One fractal: valuewhen(..., 1) is na -> no breakout possible
        res = _feed(det, [10.0, 9.0, 12.0, 11.0, 11.5, 11.6, 11.7, 13.5])
        assert res.fractal_breakout is False

    def test_no_breakout_before_any_fractal(self):
        det = FractalHalfTrendDetector()
        res = _feed(det, [10.0, 11.0, 12.0])
        assert res.fractal_breakout is False


class TestEntryExitSignals:
    """Pine: trade_entry = fractal_trend and fractal_breakout;
    trade_exit = fractal_trend[n_time] and fractal_trend == false."""

    def test_buy_signal_requires_trend_and_breakout(self):
        det = FractalHalfTrendDetector()
        res = _feed(det, _RISING)
        assert res.fractal_trend is True
        assert res.fractal_breakout is True
        assert res.buy_signal is True

    def test_no_buy_when_trend_down_despite_breakout(self):
        det = FractalHalfTrendDetector()
        res = _feed(det, _RISING_THEN_ROLLOVER)
        assert res.fractal_breakout is True
        assert res.fractal_trend is False
        assert res.buy_signal is False

    def test_sell_signal_on_trend_flip_after_n_time_bars(self):
        det = FractalHalfTrendDetector(n_time=3)
        results = []
        for i, h in enumerate(_RISING_THEN_ROLLOVER):
            results.append(det.update(_bar(h, h - 0.5, h, str(i))))
        # Trend was UP at idx15..17; when it flips (idx18) the exit fires
        assert results[18].sell_signal is True
        assert any(r.sell_signal for r in results)

    def test_no_sell_signal_without_prior_trend(self):
        det = FractalHalfTrendDetector()
        res = _feed(det, [10.0, 9.0, 12.0, 11.0, 11.5, 11.0, 10.5])
        assert res.sell_signal is False

    def test_reset_clears_state(self):
        det = FractalHalfTrendDetector()
        _feed(det, [10.0, 9.0, 12.0, 11.0, 11.5])
        det.reset()
        res = det.update(_bar(20.0, 19.5, 20.0))
        assert res.fractal_top is False
        assert res.last_fractal_price == 0.0
        assert res.fractal_average == 0.0
        assert res.fractal_trend is False
        assert res.buy_signal is False
        assert res.sell_signal is False


class TestResultContract:
    def test_result_is_frozen(self):
        res = FractalHalfTrendResult()
        with pytest.raises(Exception):
            res.buy_signal = True  # type: ignore[misc]

    def test_short_average_mode_uses_two_fractals(self):
        det = FractalHalfTrendDetector(use_longer_average=False)
        res = _feed(det, _RISING)
        # avg2 = (13.25 + 13.25) / 2 vs prior (11.25 + 13.25) / 2 -> rising
        assert res.fractal_average == pytest.approx(13.25)
        assert res.fractal_trend is True
        assert res.buy_signal is True

    def test_n_time_is_floored_at_one(self):
        det = FractalHalfTrendDetector(n_time=0)
        assert det.n_time == 1
