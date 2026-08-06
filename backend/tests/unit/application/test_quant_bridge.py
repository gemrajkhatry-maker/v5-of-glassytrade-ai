"""Unit tests for the quant→backend bridge + AuctionState serializer."""

import pytest

from app.application.services.quant_bridge import (
    QuantBridge,
    auction_state_to_dto,
    ohlc_to_quant_bar,
)
from app.domain.trading.models.value_objects import OHLC


def _ohlc(time="t1", close=100.0, high=101.0, low=99.0, open_=100.0, vol=100.0):
    return OHLC.create(
        time=time, open=open_, high=high, low=low, close=close, volume=vol,
        taker_buy_volume=60.0, delta=20.0,
    )


def test_ohlc_to_quant_bar_maps_fields():
    b = ohlc_to_quant_bar(_ohlc())
    assert b.time == "t1"
    assert b.close == 100.0
    assert b.high == 101.0
    assert b.low == 99.0
    assert b.buy_volume == 60.0
    assert b.sell_volume == pytest.approx(40.0)
    assert b.delta == 20.0


def test_bridge_returns_serialized_auction():
    br = QuantBridge()
    dto = br.on_bar_close("SYM", _ohlc())
    assert dto
    assert dto["tripleAPhase"] in ("WAITING", "ABSORBING", "ACCUMULATING", "AGGRESSION")
    assert "volumeProfile" in dto and dto["volumeProfile"]["poc"] > 0
    assert "vwap" in dto and "location" in dto and "orderFlow" in dto


def test_bridge_dedups_same_bar_time():
    br = QuantBridge()
    br.on_bar_close("SYM", _ohlc(time="t1"))
    assert br.on_bar_close("SYM", _ohlc(time="t1")) == {}  # duplicate -> no-op
    assert br.on_bar_close("SYM", _ohlc(time="t2")) != {}  # new bar -> new state


def test_bridge_reset():
    br = QuantBridge()
    br.on_bar_close("SYM", _ohlc(time="t1"))
    br.reset("SYM")
    assert br.on_bar_close("SYM", _ohlc(time="t1")) != {}  # fresh coordinator


def test_auction_state_to_dto_camel_case_keys():
    br = QuantBridge()
    dto = br.on_bar_close("SYM", _ohlc(vol=500, close=100.2))
    assert "tripleASignal" in dto
    assert "deviationSigmas" in dto["vwap"]
    assert "cvdDivergence" in dto["orderFlow"]
    assert "nearestLevel" in dto["location"]
    assert dto["absorption"] is None or "side" in dto["absorption"]
