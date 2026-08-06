"""Parity: trade_thesis via legacy shim vs moved quant module."""

from __future__ import annotations

from unittest.mock import Mock

from quant.decision.trade_thesis import (
    build_trade_thesis,
    validate_trade_thesis,
    TradeThesis,
)
from quant.contracts.enums import SetupType
from quant.contracts.value_objects import AMTResult
from tests.quant.parity import assert_parity


def _amt() -> AMTResult:
    return AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=105.0,
        value_area_low=95.0,
        prior_poc=0.0,
        prior_vah=0.0,
        prior_val=0.0,
        ib_high=0.0,
        ib_low=0.0,
        dev_poc=0.0,
        dev_vah=0.0,
        dev_val=0.0,
        leg_poc=0.0,
        leg_vah=0.0,
        leg_val=0.0,
        lvns=(),
        hvns=(),
        session_vwap=0.0,
        aggression=0.8,
        cvd_slope=0.5,
        ofi=0.0,
        liquidity_sweep="",
        lvn_play=None,
        break_type="",
    )


def _tick():
    from quant.contracts.value_objects import OHLC
    return OHLC(time="2026-01-01T00:00:00Z", open=100.0, high=101.0, low=99.0,
                close=100.0, volume=500, vwap=99.0, delta=100)


def test_build_trade_thesis_parity():
    kwargs = dict(tick=_tick(), amt_result=_amt(), setup_type=SetupType.MEAN_REVERSION,
                  session_context="NSE_PRIMARY", invalidation_level=95.0)
    build_trade_thesis(**kwargs)


def test_validate_trade_thesis_parity():
    thesis = TradeThesis(
        market_state="BALANCED",
        location_type="VAL",
        location_level=95.0,
        aggression_trigger="DELTA_EXPANSION",
        session_context="NSE_PRIMARY",
        invalidation_level=95.0,
        setup_family="return_to_value",
    )
    validate_trade_thesis(thesis)


def test_validate_trade_thesis_none_parity():
    validate_trade_thesis(None)


def test_validate_trade_thesis_dict_parity():
    d = dict(market_state="BALANCED", location_type="VAL", location_level=95.0,
             aggression_trigger="DELTA_EXPANSION", session_context="NSE_PRIMARY",
             invalidation_level=95.0, setup_family="return_to_value")
    validate_trade_thesis(d)


def test_validate_trade_thesis_incomplete_parity():
    thesis = TradeThesis(
        market_state="", location_type="MID_RANGE", location_level=0.0,
        aggression_trigger="", session_context="", invalidation_level=0.0,
        setup_family="",
    )
    validate_trade_thesis(thesis)
