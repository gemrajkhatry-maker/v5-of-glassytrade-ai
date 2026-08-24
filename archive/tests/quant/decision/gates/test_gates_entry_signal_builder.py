"""Tests for entry-gate signal_builder — ported from backend tests.

Covers build_entry_signal + sl_from_aggressive_print (Fabio entry-gate
signal builder). Distinct from the greenfield quant.decision.signal_builder
(5-gate SignalBuilder) — this is the backend entry-gates version.
"""

import pytest

from quant.contracts.enums import SetupType, SignalType, Source
from quant.contracts.value_objects import OHLC, AMTResult, AggressivePrint
from quant.decision.gates.signal_builder import (
    build_entry_signal,
    sl_from_aggressive_print,
)


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(market_state="BALANCED", poc=100, vah=105, val=95, lvns=(), hvns=(),
         aggression=0.5, session_vwap=0, aggressive_prints=(), cvd_slope=0.0,
         profile_shape=""):
    return AMTResult(
        market_state=market_state, poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=lvns, hvns=hvns, aggression=aggression,
        session_vwap=session_vwap, aggressive_prints=aggressive_prints,
        cvd_slope=cvd_slope, profile_shape=profile_shape,
    )


class TestBuildEntrySignal:
    def test_long_trend_signal(self):
        tick = _tick(close=100, vwap=99)
        amt = _amt(poc=100, vah=105, val=95, session_vwap=99)
        ai = {"rationale": "test reason", "confidence": "High"}
        sig = build_entry_signal("LONG", tick, amt, ai, SetupType.TREND_MODEL)
        assert sig.type == SignalType.BUY
        assert sig.source == Source.LLM
        assert sig.stop_loss < sig.price < sig.take_profit
        assert sig.metadata["allow_trail"] is True

    def test_short_mean_reversion_signal(self):
        tick = _tick(close=105, vwap=100)
        amt = _amt(poc=100, vah=105, val=95, session_vwap=100)
        ai = {"rationale": "test", "confidence": "Medium"}
        sig = build_entry_signal("SHORT", tick, amt, ai, SetupType.MEAN_REVERSION)
        assert sig.type == SignalType.SELL
        assert sig.metadata["allow_trail"] is False

    def test_signal_contains_trade_thesis_metadata(self):
        tick = _tick(close=95, vwap=99)
        amt = _amt(poc=100, vah=105, val=95, session_vwap=99, aggression=0.8, cvd_slope=0.5)
        ai = {"rationale": "value reclaim", "confidence": "High"}
        sig = build_entry_signal(
            "LONG",
            tick,
            amt,
            ai,
            SetupType.MEAN_REVERSION,
            session_context="NSE_PRIMARY",
        )

        thesis = sig.metadata["trade_thesis"]
        assert thesis["market_state"] == "BALANCED"
        assert thesis["location_type"] == "VAL"
        assert thesis["aggression_trigger"] in {"DELTA_EXPANSION", "CVD_EXPANSION", "DELTA_PRESSURE"}
        assert thesis["session_context"] == "NSE_PRIMARY"
        assert thesis["invalidation_level"] == sig.stop_loss


class TestSLFromAggressivePrint:
    def test_long_uses_sell_print(self):
        tick = _tick(close=100)
        ap = AggressivePrint(price=99.6, time="t", volume=500, delta=-200, side="SELL")
        amt = _amt(aggressive_prints=(ap,))
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl == pytest.approx(99.5)

    def test_no_prints_returns_none(self):
        amt = _amt(aggressive_prints=())
        assert sl_from_aggressive_print(amt, _tick(), True, 0.1) is None

    def test_ignores_distant_prints(self):
        tick = _tick(close=100)
        ap = AggressivePrint(price=90, time="t", volume=500, delta=-200, side="SELL")
        amt = _amt(aggressive_prints=(ap,))
        assert sl_from_aggressive_print(amt, tick, True, 0.1) is None

    def test_picks_nearest_sell_print_for_long(self):
        prints = [
            AggressivePrint(price=99.60, time="t1", side="SELL", volume=100, delta=-50),
            AggressivePrint(price=99.70, time="t2", side="SELL", volume=100, delta=-50),
            AggressivePrint(price=99.80, time="t3", side="SELL", volume=100, delta=-50),
        ]
        amt = _amt(aggressive_prints=tuple(prints))
        tick = _tick(close=100.0)
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl is not None
        assert sl == pytest.approx(99.80 - 0.1)

    def test_picks_nearest_buy_print_for_short(self):
        prints = [
            AggressivePrint(price=100.10, time="t1", side="BUY", volume=100, delta=50),
            AggressivePrint(price=100.20, time="t2", side="BUY", volume=100, delta=50),
            AggressivePrint(price=100.40, time="t3", side="BUY", volume=100, delta=50),
        ]
        amt = _amt(aggressive_prints=tuple(prints))
        tick = _tick(close=100.0)
        sl = sl_from_aggressive_print(amt, tick, is_buy=False, buffer=0.1)
        assert sl is not None
        assert sl == pytest.approx(100.10 + 0.1)

    def test_returns_none_when_no_opposing_prints(self):
        prints = [AggressivePrint(price=101.0, time="t1", side="BUY", volume=100, delta=50)]
        amt = _amt(aggressive_prints=tuple(prints))
        tick = _tick(close=100.0)
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl is None


class TestCushionSL:
    def test_risk_sl_pct_tightens_stop(self):
        tick = _tick(100.0)
        amt = _amt()
        ai_result = {"direction": "LONG", "confidence": "HIGH", "rationale": "test"}
        sig = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL, risk_sl_pct=0.005
        )
        assert sig.stop_loss is not None

    def test_risk_sl_pct_none_no_change(self):
        tick = _tick(100.0)
        amt = _amt()
        ai_result = {"direction": "LONG", "confidence": "HIGH", "rationale": "test"}
        sig_default = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL
        )
        sig_none = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL, risk_sl_pct=None
        )
        assert sig_default.stop_loss == sig_none.stop_loss

    def test_risk_sl_respects_wider_quant(self):
        tick = _tick(100.0)
        amt = _amt()
        ai_result = {"direction": "LONG", "confidence": "HIGH", "rationale": "test"}
        sig_wide = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL, risk_sl_pct=0.10
        )
        sig_default = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL
        )
        assert sig_wide.stop_loss == sig_default.stop_loss
