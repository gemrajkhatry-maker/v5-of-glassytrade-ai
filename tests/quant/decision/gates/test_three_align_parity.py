"""Parity: three_align via legacy shim vs moved quant module.

three_align_check consumes a ThreeAlignInput protocol — AMTResult (quant.contracts)
implements it, and is also the legacy value object (re-exported), so the same
object can be passed to both sides.
"""

from __future__ import annotations

from unittest.mock import Mock

from quant.decision.gates.three_align import (
    three_align_check,
    cluster_aggressive_prints,
    min_candles_gate,
    full_body_close_gate,
    nearest_round_number,
)
from quant.contracts.value_objects import OHLC, AggressivePrint, AMTResult
from tests.quant.parity import assert_parity


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0, open=None):
    h = high or close * 1.01
    l = low or close * 0.99
    o = open if open is not None else close
    return OHLC(time="2026-01-01T00:00:00Z", open=o, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(poc=100, vah=105, val=95, **kw):
    return AMTResult(
        market_state=kw.get("market_state", "BALANCED"), poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=kw.get("lvns", ()), hvns=kw.get("hvns", ()),
        aggression=kw.get("aggression", 0.5),
        session_vwap=kw.get("session_vwap", 0),
        cvd_slope=kw.get("cvd_slope", 0.0),
        cvd_divergence=kw.get("cvd_divergence", ""),
        price_velocity=kw.get("price_velocity", 0.0),
        leg_poc=kw.get("leg_poc", 0.0),
        leg_vah=kw.get("leg_vah", 0.0),
        leg_val=kw.get("leg_val", 0.0),
        leg_lvns=kw.get("leg_lvns", ()),
        dev_poc=kw.get("dev_poc", 0.0),
        dev_vah=kw.get("dev_vah", 0.0),
        dev_val=kw.get("dev_val", 0.0),
    )


def test_three_align_pass_parity():
    data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
    tick = _tick(close=100, volume=500, delta=200)
    amt = _amt(poc=100, vah=105, val=95)
    three_align_check(data, amt, tick)


def test_three_align_fail_parity():
    data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
    tick = _tick(close=110, volume=500, delta=200)
    amt = _amt(poc=100, vah=105, val=95)
    three_align_check(data, amt, tick)


def test_three_align_golden_mock_parity():
    amt = Mock(
        poc=22450.0,
        value_area_high=22520.0,
        value_area_low=22380.0,
        cvd_slope=2.7,
        session_vwap=22465.0,
        market_state="BALANCED",
        price_velocity=0.08,
        leg_poc=22480.0,
        leg_vah=22530.0,
        leg_val=22420.0,
        dev_poc=22430.0,
        dev_vah=22510.0,
        dev_val=22390.0,
        hvns=[22550.0],
        lvns=[22350.0],
        leg_lvns=[],
    )
    tick = Mock(
        close=22455.0,
        high=22465.0,
        low=22445.0,
        open=22450.0,
        vwap=22465.0,
        time="2026-05-04T10:30:00Z",
    )
    data = [Mock(time="2026-05-04T10:29:00Z")] * 30
    three_align_check(data, amt, tick)


def test_cluster_aggressive_prints_parity():
    prints = (
        AggressivePrint(price=100.0, time="t", volume=300, delta=100, side="BUY"),
        AggressivePrint(price=100.05, time="t", volume=200, delta=50, side="BUY"),
        AggressivePrint(price=105.0, time="t", volume=200, delta=50, side="BUY"),
    )
    cluster_aggressive_prints(prints)
    cluster_aggressive_prints(())


def test_min_candles_parity():
    min_candles_gate([1, 2, 3, 4, 5, 6], 6)
    min_candles_gate([1, 2, 3], 6)


def test_full_body_close_parity():
    tick = _tick(close=101, open=100, high=101.5, low=99.5)
    full_body_close_gate(tick, 100.5, "LONG")
    tick2 = _tick(close=99, open=100, high=100.5, low=98.5)
    full_body_close_gate(tick2, 99.5, "SHORT")


def test_nearest_round_number_parity():
    for price in (950, 540, 5200, 8800, 15200, 500):
        nearest_round_number(price)
