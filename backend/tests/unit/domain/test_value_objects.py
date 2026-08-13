"""Unit tests for domain value objects — immutability, creation, defaults."""

import pytest
from quant.contracts.value_objects import (
    OHLC, OrderBookLevel, OrderBook, VolumeProfileLevel,
    StrategyStats,
    FootprintLevel, FootprintCandle, AICommandResponse, AggressivePrint,
)

class TestOHLC:
    def test_create_basic(self):
        o = OHLC(time="2026-01-01T00:00:00Z", open=100, high=110,
                 low=90, close=105, volume=1000, vwap=103)
        assert o.close == 105
        assert o.delta == 0.0
        assert o.taker_buy_volume == 0.0

    def test_frozen(self):
        o = OHLC(time="t", open=1, high=2, low=0.5, close=1.5,
                 volume=100, vwap=1.3)
        with pytest.raises(AttributeError):
            o.close = 999  # type: ignore

    def test_all_fields(self):
        o = OHLC(time="t", open=1, high=2, low=0.5, close=1.5,
                 volume=100, vwap=1.3, taker_buy_volume=60, delta=20)
        assert o.taker_buy_volume == 60
        assert o.delta == 20


class TestOrderBook:
    def test_empty_book(self):
        ob = OrderBook()
        assert ob.bids == ()
        assert ob.asks == ()

    def test_with_levels(self):
        ob = OrderBook(
            bids=(OrderBookLevel(price=100, quantity=5),),
            asks=(OrderBookLevel(price=101, quantity=3),),
        )
        assert len(ob.bids) == 1
        assert ob.asks[0].price == 101

    def test_frozen(self):
        ob = OrderBook()
        with pytest.raises(AttributeError):
            ob.bids = ()  # type: ignore


class TestStrategyStats:
    def test_defaults(self):
        s = StrategyStats()
        assert s.total_trades == 0
        assert s.win_rate == 0.0


class TestFootprint:
    def test_level(self):
        fl = FootprintLevel(price=100, bid=50, ask=80, delta=30, imbalance=True)
        assert fl.imbalance

    def test_candle(self):
        fc = FootprintCandle(
            time="t",
            levels=(FootprintLevel(price=100, bid=50, ask=80, delta=30),),
            poc_price=100, total_delta=30, step_price=0.5,
        )
        assert len(fc.levels) == 1


class TestAggressivePrint:
    def test_create(self):
        ap = AggressivePrint(price=100, time="t", side="BUY", volume=500, delta=200)
        assert ap.side == "BUY"


class TestAICommandResponse:
    def test_create(self):
        r = AICommandResponse(message="Done", action="RESET")
        assert r.config_updates is None


class TestVolumeProfileLevel:
    def test_mutable(self):
        vp = VolumeProfileLevel(price=100)
        vp.volume += 50
        assert vp.volume == 50
