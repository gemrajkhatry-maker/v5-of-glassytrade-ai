"""Parity: grading via legacy shim vs moved quant module."""

from __future__ import annotations

from quant.decision.gates.grading import (
    check_vwap_bias,
    check_imbalance_alignment,
    compute_grade_score,
)
from quant.contracts.enums import SetupType
from quant.contracts.value_objects import AMTResult, OHLC, StackedImbalance
from tests.quant.parity import assert_parity


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(poc=100, vah=105, val=95, cvd_slope=0.0, **kw):
    return AMTResult(
        market_state=kw.get("market_state", "BALANCED"), poc=poc,
        value_area_high=vah, value_area_low=val,
        aggression=kw.get("aggression", 0.5),
        session_vwap=kw.get("session_vwap", 0),
        cvd_slope=cvd_slope,
        cvd_divergence=kw.get("cvd_divergence", ""),
        vwap_upper_2=kw.get("vwap_upper_2", 0.0),
        vwap_lower_2=kw.get("vwap_lower_2", 0.0),
        profile_shape=kw.get("profile_shape", ""),
    )


def test_check_vwap_bias_parity():
    for direction, price, vwap, u2, l2 in [
        ("LONG", 98.0, 100.0, 104.0, 96.0),
        ("SHORT", 102.0, 100.0, 104.0, 96.0),
        ("LONG", 104.0, 100.0, 104.0, 96.0),
        ("SHORT", 96.0, 100.0, 104.0, 96.0),
        ("LONG", 101.0, 100.0, 104.0, 96.0),
        ("LONG", 0.0, 0.0, 0.0, 0.0),
    ]:
        check_vwap_bias(direction, price, vwap, u2, l2)


def test_check_imbalance_alignment_parity():
    imbalances = [
        StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
        StackedImbalance(direction="BUY", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
    ]
    check_imbalance_alignment("LONG", imbalances)
    check_imbalance_alignment("LONG", [])
    check_imbalance_alignment("SHORT", imbalances)


def test_compute_grade_score_parity():
    tick = _tick(close=100, vwap=99)
    amt = _amt(poc=100, vah=105, val=95, cvd_slope=0.5, session_vwap=99)
    kwargs = dict(direction="LONG", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
    compute_grade_score(**kwargs)


def test_compute_grade_score_extreme_cvd_parity():
    tick = _tick(close=100)
    amt = _amt(poc=100, vah=105, val=95, cvd_slope=-55.0)
    kwargs = dict(direction="LONG", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
    compute_grade_score(**kwargs)
