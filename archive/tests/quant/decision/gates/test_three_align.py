"""Tests for three_align — ported from backend/tests/unit/domain/test_entry_gate.py."""

from quant.contracts.value_objects import OHLC, AggressivePrint, AMTResult
from quant.decision.gates.three_align import (
    three_align_check,
    cluster_aggressive_prints,
    nearest_round_number,
    min_candles_gate,
    full_body_close_gate,
    extract_bubble_levels_from_footprint,
)


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0, open=None):
    h = high or close * 1.01
    l = low or close * 0.99
    o = open if open is not None else close
    return OHLC(time="2026-01-01T00:00:00Z", open=o, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(market_state="BALANCED", poc=100, vah=105, val=95, lvns=(), hvns=(),
         aggression=0.5, session_vwap=0, aggressive_prints=(), cvd_slope=0.0):
    return AMTResult(
        market_state=market_state, poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=lvns, hvns=hvns, aggression=aggression,
        session_vwap=session_vwap, aggressive_prints=aggressive_prints,
        cvd_slope=cvd_slope,
    )


class TestThreeAlignCheck:
    def test_passes_when_all_align(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick)[0] is True

    def test_fails_zero_poc(self):
        data = [_tick() for _ in range(30)]
        tick = _tick()
        amt = _amt(poc=0, vah=0, val=0)
        assert three_align_check(data, amt, tick)[0] is False

    def test_fails_not_near_level(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=110, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick)[0] is False

    def test_passes_near_lvn(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=98, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95, lvns=(98.0,))
        assert three_align_check(data, amt, tick)[0] is True

    def test_absorption_plus_breakout_confirms_weak_bundle(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=100, delta=5)
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick)[0] is False
        assert (
            three_align_check(
                data,
                amt,
                tick,
                absorption_detected=True,
                vwap_breakout="LONG",
            )[0]
            is True
        )

    def test_absorption_without_breakout_does_not_confirm(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=100, delta=5)
        amt = _amt(poc=100, vah=105, val=95)
        assert (
            three_align_check(
                data,
                amt,
                tick,
                absorption_detected=True,
                vwap_breakout=None,
            )[0]
            is False
        )


class TestThreeAlignAggressiveLevels:
    def test_near_aggressive_level(self):
        """Price near an aggressive print cluster level counts as near level."""
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=110, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick)[0] is False
        assert three_align_check(data, amt, tick, aggressive_levels=[110])[0] is True

    def test_existing_levels_still_work(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick, aggressive_levels=None)[0] is True


class TestClusterAggressivePrints:
    def test_merges_nearby(self):
        prints = (
            AggressivePrint(price=100.0, time="t", volume=300, delta=100, side="BUY"),
            AggressivePrint(price=100.05, time="t", volume=200, delta=50, side="BUY"),
        )
        result = cluster_aggressive_prints(prints)
        assert len(result) == 1
        assert result[0] == 100.02

    def test_separate_far(self):
        prints = (
            AggressivePrint(price=100.0, time="t", volume=300, delta=100, side="BUY"),
            AggressivePrint(price=105.0, time="t", volume=200, delta=50, side="BUY"),
        )
        result = cluster_aggressive_prints(prints)
        assert len(result) == 2

    def test_cap_at_5(self):
        prints = tuple(
            AggressivePrint(price=100.0 + i * 10, time="t", volume=(i + 1) * 100, delta=50, side="BUY")
            for i in range(7)
        )
        result = cluster_aggressive_prints(prints)
        assert len(result) == 5

    def test_empty(self):
        assert cluster_aggressive_prints(()) == []


class TestNearestRoundNumber:
    def test_below_1000(self):
        assert nearest_round_number(950) == 1000
        assert nearest_round_number(540) == 500

    def test_below_10000(self):
        assert nearest_round_number(5200) == 5000
        assert nearest_round_number(8800) == 9000

    def test_above_10000(self):
        assert nearest_round_number(15200) == 15000

    def test_amt_analyzer_cases(self):
        assert nearest_round_number(6130) == 6000
        assert nearest_round_number(6350) == 6500
        assert nearest_round_number(98) == 100
        assert nearest_round_number(12500) == 12000
        assert nearest_round_number(12400) == 12000


class TestMinCandlesGate:
    def test_enough_candles(self):
        assert min_candles_gate([1, 2, 3, 4, 5, 6]) is True

    def test_insufficient_candles(self):
        assert min_candles_gate([1, 2, 3]) is False


class TestFullBodyCloseGate:
    def test_long_full_body_above(self):
        tick = _tick(close=101, open=100, high=101.5, low=99.5)
        assert full_body_close_gate(tick, break_level=100.5, direction="LONG") is True

    def test_short_full_body_below(self):
        tick = _tick(close=99, open=100, high=100.5, low=98.5)
        assert full_body_close_gate(tick, break_level=99.5, direction="SHORT") is True

    def test_small_body_fails(self):
        tick = _tick(close=100.6, open=100.5, high=101, low=99.5)
        assert full_body_close_gate(tick, break_level=100.5, direction="LONG") is False

    def test_wick_heavy_doji_fails(self):
        doji = _tick(close=100, open=100, high=105, low=95)
        assert full_body_close_gate(doji, 99, "LONG") is False

    def test_bullish_body_close_below_level_fails(self):
        bull = _tick(close=100, open=98, high=101, low=98)
        assert full_body_close_gate(bull, 102, "LONG") is False

    def test_bearish_full_body_close(self):
        bear = _tick(close=98, open=100, high=100, low=97)
        assert full_body_close_gate(bear, 99, "SHORT") is True


class TestExtractBubbleLevelsFromFootprint:
    def test_empty_domain(self):
        assert extract_bubble_levels_from_footprint(None) == []
        assert extract_bubble_levels_from_footprint({}) == []

    def test_extracts_stacked_levels(self):
        class _Level:
            def __init__(self, price, stacked):
                self.price = price
                self.stacked = stacked

        class _Candle:
            def __init__(self, levels):
                self.levels = levels

        fp = {"c1": _Candle([_Level(100.0, True), _Level(101.0, False)]),
              "c2": _Candle([_Level(102.0, True)])}
        levels = extract_bubble_levels_from_footprint(fp)
        assert 100.0 in levels
        assert 102.0 in levels
        assert 101.0 not in levels
