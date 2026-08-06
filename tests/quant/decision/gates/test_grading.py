"""Tests for grading — ported from backend/tests/unit/domain/test_entry_gate.py."""

import pytest

from quant.contracts.enums import SetupType
from quant.contracts.value_objects import AMTResult, OHLC, StackedImbalance
from quant.decision.gates.grading import (
    check_vwap_bias,
    check_imbalance_alignment,
    compute_grade_score,
)


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
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


class TestCheckVWAPBias:
    def test_long_below_vwap_warning(self):
        result = check_vwap_bias("LONG", price=98.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_short_above_vwap_warning(self):
        result = check_vwap_bias("SHORT", price=102.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_long_at_vwap_2sigma_overextended(self):
        result = check_vwap_bias("LONG", price=104.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["overextended"] is True

    def test_short_at_vwap_minus_2sigma_overextended(self):
        result = check_vwap_bias("SHORT", price=96.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["overextended"] is True

    def test_long_above_vwap_no_warning(self):
        result = check_vwap_bias("LONG", price=101.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["warning"] is False
        assert result["overextended"] is False


class TestImbalanceAlignment:
    def test_aligned_long_buy_imbalances(self):
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="BUY", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 1

    def test_opposing_long_sell_imbalances(self):
        imbalances = [
            StackedImbalance(direction="SELL", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="SELL", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == -2

    def test_empty_imbalances(self):
        assert check_imbalance_alignment("LONG", []) == 0

    def test_mixed_equal_imbalances(self):
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="SELL", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 0

    def test_short_aligned_with_sell(self):
        imbalances = [
            StackedImbalance(direction="SELL", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="SELL", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
            StackedImbalance(direction="BUY", price_low=98, price_high=100, magnitude=2, candle_time="t3"),
        ]
        assert check_imbalance_alignment("SHORT", imbalances) == 1

    def test_short_opposing_buy_imbalances(self):
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
        ]
        assert check_imbalance_alignment("SHORT", imbalances) == -2


class TestCVDHardGate:
    def test_long_extreme_bearish_cvd_blocked(self):
        tick = _tick(close=100)
        amt = _amt(poc=100, vah=105, val=95, cvd_slope=-55.0)
        score = compute_grade_score(direction="LONG", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
        assert score == -10

    def test_short_extreme_bullish_cvd_blocked(self):
        tick = _tick(close=100)
        amt = _amt(poc=100, vah=105, val=95, cvd_slope=55.0)
        score = compute_grade_score(direction="SHORT", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
        assert score == -10

    def test_normal_cvd_passes_gate(self):
        tick = _tick(close=100)
        amt = _amt(poc=100, vah=105, val=95, cvd_slope=10.0)
        score = compute_grade_score(direction="LONG", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
        assert score != -10
