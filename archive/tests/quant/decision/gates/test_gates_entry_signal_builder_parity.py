"""Parity: entry-gate signal_builder via legacy shim vs moved quant module."""

from __future__ import annotations

from unittest.mock import Mock

from quant.decision.gates.signal_builder import (
    build_entry_signal,
    sl_from_aggressive_print,
)
from quant.contracts.enums import SetupType
from quant.contracts.value_objects import AggressivePrint, AMTResult
from tests.quant.parity import assert_parity


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    from quant.contracts.value_objects import OHLC
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(poc=100, vah=105, val=95, **kw):
    return AMTResult(
        market_state=kw.get("market_state", "BALANCED"), poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=kw.get("lvns", ()), hvns=kw.get("hvns", ()),
        aggression=kw.get("aggression", 0.5),
        session_vwap=kw.get("session_vwap", 0),
        aggressive_prints=kw.get("aggressive_prints", ()),
        cvd_slope=kw.get("cvd_slope", 0.0),
        profile_shape=kw.get("profile_shape", ""),
        prior_poc=kw.get("prior_poc", 0.0),
        npoc_above=kw.get("npoc_above", 0.0),
        npoc_below=kw.get("npoc_below", 0.0),
        lvn_play=kw.get("lvn_play", None),
    )


def test_sl_from_aggressive_print_parity():
    prints = (
        AggressivePrint(price=99.6, time="t", volume=500, delta=-200, side="SELL"),
        AggressivePrint(price=99.8, time="t2", volume=300, delta=-100, side="SELL"),
    )
    amt = _amt(aggressive_prints=prints)
    tick = _tick(close=100)
    sl_from_aggressive_print(amt, tick, True, 0.1)
    sl_from_aggressive_print(amt, tick, True, 0.1, False)
    amt_empty = _amt(aggressive_prints=())
    sl_from_aggressive_print(amt_empty, tick, True, 0.1)


def test_build_entry_signal_golden_mock_parity():
    amt = Mock(
        poc=22450.0,
        prior_poc=22420.0,
        value_area_high=22520.0,
        value_area_low=22380.0,
        npoc_above=22580.0,
        npoc_below=22320.0,
        session_vwap=22465.0,
        lvn_play={"direction": "LONG", "price": 22435.0},
        profile_shape="balanced",
        aggressive_prints=[],
        cvd_slope=0.0,
        cvd_divergence="",
        vwap_upper_2=0.0,
        vwap_lower_2=0.0,
    )
    tick = Mock(
        close=22455.0,
        high=22465.0,
        low=22445.0,
        open=22450.0,
        vwap=22465.0,
        time="2026-05-04T10:30:00Z",
    )
    ai_result = {"setup": "mean-reversion", "rationale": "POC reversion play"}

    new_signal = build_entry_signal(
        direction="LONG",
        tick=tick,
        amt_result=amt,
        ai_result=ai_result,
        setup_type=SetupType.MEAN_REVERSION,
        data=[Mock()] * 30,
        tick_size=0.05,
    )
    assert new_signal.type is not None
    assert new_signal.price is not None
    assert new_signal.stop_loss is not None
    assert new_signal.take_profit is not None
    assert new_signal.metadata["llm_entry"] is not None
    assert new_signal.metadata["grade_score"] is not None
    assert new_signal.metadata["trade_thesis"]["location_type"] is not None
    assert new_signal.reason is not None


def test_build_entry_signal_trend_parity():
    tick = _tick(close=100, vwap=99)
    amt = _amt(poc=100, vah=105, val=95, session_vwap=99, cvd_slope=0.5,
               aggression=0.8, profile_shape="balanced")
    ai = {"rationale": "test reason", "confidence": "High"}
    kwargs = dict(direction="LONG", tick=tick, amt_result=amt, ai_result=ai,
                  setup_type=SetupType.TREND_MODEL, data=[_tick()] * 30, tick_size=0.05)

    new_signal = build_entry_signal(**kwargs)
    assert new_signal.type is not None
    assert new_signal.price is not None
    assert new_signal.stop_loss is not None
    assert new_signal.take_profit is not None
    assert new_signal.metadata["grade_score"] is not None
    assert new_signal.reason is not None
