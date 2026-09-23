"""Tests for the HalfTrend detector (everget Pine v6 port).

Each scenario mirrors the Pine state machine: rails seed from bar-0
nz(..., current), the up flip requires ``lowma > minHighPrice and
close > high[1]`` while ``nextTrend == 0``, the down flip requires
``highma < maxLowPrice and close < low[1]`` while ``nextTrend == 1``,
arrows only appear on bars where the trend actually flips, and channel
width = channelDeviation * (rma(tr, atr_period) / 2).
"""

import pytest

from quant.amt.market.half_trend import (
    HalfTrendDetector,
    compute_half_trend_series,
)
from quant.contracts.value_objects import OHLC


def _bar(h: float, lo: float, c: float, t: str) -> OHLC:
    return OHLC.create(time=t, open=c, high=h, low=lo, close=c, volume=100)


def _feed(det: HalfTrendDetector, bars: list[OHLC]):
    last = None
    for b in bars:
        last = det.update(b)
    return last


# Sequence forcing a real down flip then a real up flip:
#   b0..b2  flat 100
#   b3..b4  drift lower
#   b7      down flip (close < low[1], highma < maxLowPrice) -> SELL
#   b11     up flip   (close > high[1], lowma > minHighPrice) -> BUY
_FLIP_SEQ = [
    _bar(100.0, 100.0, 100.0, "t0"),
    _bar(99.0, 99.0, 99.0, "t1"),
    _bar(98.0, 98.0, 98.0, "t2"),
    _bar(97.0, 97.0, 97.0, "t3"),
    _bar(99.5, 99.4, 99.4, "t4"),
    _bar(100.0, 99.0, 99.0, "t5"),
    _bar(99.0, 98.0, 98.0, "t6"),
    _bar(98.0, 97.0, 97.0, "t7"),   # down flip -> sell signal
    _bar(97.0, 96.0, 96.0, "t8"),
    _bar(96.0, 95.0, 95.0, "t9"),
    _bar(99.0, 98.5, 98.7, "t10"),
    _bar(100.0, 99.0, 99.5, "t11"),  # up flip -> buy signal
]


class TestWarmUpAndFlatMarket:
    def test_flat_market_never_flips(self):
        det = HalfTrendDetector(atr_period=3)
        res = _feed(det, [_bar(100.0, 100.0, 100.0, f"t{i}") for i in range(30)])
        assert res.trend == 0
        assert res.ht == pytest.approx(100.0)
        assert res.buy_signal is False
        assert res.sell_signal is False

    def test_bar_zero_ht_seeds_from_low(self):
        det = HalfTrendDetector(atr_period=3)
        res = det.update(_bar(105.0, 95.0, 100.0, "t0"))
        # Pine: maxLowPrice := nz(low[1], low) -> bar-0 low -> ht = up = low
        assert res.trend == 0
        assert res.ht == pytest.approx(95.0)
        assert res.atr_high is None  # no ATR before a second bar (TR undefined)
        assert res.atr_low is None

    def test_atr_channels_warm_after_period_trues(self):
        det = HalfTrendDetector(atr_period=3)
        _feed(det, [_bar(100.0, 100.0, 100.0, f"t{i}") for i in range(3)])
        res = det.update(_bar(100.0, 100.0, 100.0, "t3"))
        assert res.atr_high is not None
        assert res.atr_low is not None
        # channel symmetric around ht: dev = channelDeviation * (atr / 2)
        dev = res.atr_high - res.ht
        assert res.ht - res.atr_low == pytest.approx(dev)
        assert dev == pytest.approx(0.0)  # flat bars -> TR = 0 -> dev = 0
        assert res.buy_signal is False
        assert res.sell_signal is False


class TestFlipsAndSignals:
    def test_down_flip_emits_sell(self):
        det = HalfTrendDetector(atr_period=3)
        res = _feed(det, _FLIP_SEQ[:8])
        assert res.trend == 1
        assert res.sell_signal is True
        assert res.buy_signal is False

    def test_up_flip_emits_buy(self):
        det = HalfTrendDetector(atr_period=3)
        res = _feed(det, _FLIP_SEQ)
        assert res.trend == 0
        assert res.buy_signal is True
        assert res.sell_signal is False
        # up rail re-anchors to the previous down rail on the flip bar
        # (Pine: up := down[1]) — the down rail was 97 at t8..t10.
        assert res.ht == pytest.approx(97.0)

    def test_initial_phase_up_leg_produces_no_buy(self):
        det = HalfTrendDetector(atr_period=3)
        # t4 marks the first up flip, but trend never was 1 -> no signal
        res = _feed(det, _FLIP_SEQ[:5])
        assert res.trend == 0
        assert res.buy_signal is False
        assert res.sell_signal is False

    def test_signals_are_single_bar_events(self):
        det = HalfTrendDetector(atr_period=3)
        rows = [det.update(b) for b in _FLIP_SEQ]
        sells = [i for i, r in enumerate(rows) if r.sell_signal]
        buys = [i for i, r in enumerate(rows) if r.buy_signal]
        assert sells == [7]
        assert buys == [11]

    def test_down_flip_rail_ratchets(self):
        det = HalfTrendDetector(atr_period=3)
        res = _feed(det, _FLIP_SEQ[:8])
        # down rail = previous up rail (100) then ratchets down with
        # minHighPrice on the bars that follow the flip.
        assert res.ht == pytest.approx(100.0)
        res2 = det.update(_FLIP_SEQ[8])
        assert res2.ht == pytest.approx(98.0)
        res3 = det.update(_FLIP_SEQ[9])
        assert res3.ht == pytest.approx(97.0)


class TestSeriesAndLifecycle:
    def test_stateless_series_matches_detector_replay(self):
        rows = compute_half_trend_series(_FLIP_SEQ, atr_period=3)
        assert len(rows) == len(_FLIP_SEQ)
        det = HalfTrendDetector(atr_period=3)
        live = [det.update(b) for b in _FLIP_SEQ]
        for a, b in zip(rows, live):
            assert a == b
        assert rows[-1].buy_signal is True

    def test_warm_up_then_update_extends_series(self):
        det = HalfTrendDetector(atr_period=3)
        det.warm_up(_FLIP_SEQ)
        assert det.warmed is True
        # warm_up replays everything except the last bar; the next update
        # consumes the last bar and must equal the full stateless series end.
        tail = det.update(_FLIP_SEQ[-1])
        rows = compute_half_trend_series(_FLIP_SEQ, atr_period=3)
        assert tail == rows[-1]

    def test_update_is_idempotent_per_bar_time(self):
        det = HalfTrendDetector(atr_period=3)
        first = det.update(_FLIP_SEQ[0])
        dup = det.update(_FLIP_SEQ[0])  # same time — must not double-advance
        assert dup == first
        # feeding the remainder after the duplicate must equal a clean replay
        det2 = HalfTrendDetector(atr_period=3)
        clean = [det2.update(b) for b in _FLIP_SEQ]
        after_dup = [first, *[det.update(b) for b in _FLIP_SEQ[1:]]]
        assert after_dup == clean

    def test_reset_returns_to_bar_zero_state(self):
        det = HalfTrendDetector(atr_period=3)
        _feed(det, _FLIP_SEQ)
        det.reset()
        res = det.update(_bar(105.0, 95.0, 100.0, "again"))
        assert res.trend == 0
        assert res.ht == pytest.approx(95.0)
        assert res.buy_signal is False
        assert res.sell_signal is False

    def test_result_is_frozen(self):
        from dataclasses import FrozenInstanceError
        rows = compute_half_trend_series([_FLIP_SEQ[0]], atr_period=3)
        with pytest.raises(FrozenInstanceError):
            rows[0].trend = 1  # type: ignore[misc]
