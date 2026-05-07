"""Integration tests for WebSocket & viewer flow — server-driven viewer loop, state serialization."""

from __future__ import annotations

import pytest
import json
from app.api.websocket.gameloop import (
    _compute_delta,
    _deep_equal,
    _validate_tick,
    _parse_tick,
    _parse_order_book,
)
from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel


class TestDeltaCompression:
    """Test delta compression for state updates."""

    def test_first_send_returns_full_state(self):
        """No previous state → full state returned."""
        state = {"symbol": "NIFTY", "price": 22500.0, "volume": 100}
        delta = _compute_delta(None, state)
        assert delta == state

    def test_unchanged_state_returns_empty(self):
        """No changes → empty delta."""
        state = {"symbol": "NIFTY", "price": 22500.0}
        delta = _compute_delta(state, state)
        assert delta == {"_symbol": "NIFTY", "_type": "delta"} or delta == {}

    def test_changed_key_in_delta(self):
        """Changed key appears in delta."""
        prev = {"symbol": "NIFTY", "price": 22500.0}
        curr = {"symbol": "NIFTY", "price": 22510.0}
        delta = _compute_delta(prev, curr)
        assert "price" in delta

    def test_unchanged_key_not_in_delta(self):
        """Unchanged key not in delta."""
        prev = {"symbol": "NIFTY", "price": 22500.0}
        curr = {"symbol": "NIFTY", "price": 22510.0}
        delta = _compute_delta(prev, curr)
        assert "symbol" not in delta

    def test_nested_dict_change_detected(self):
        """Nested dict change detected by deep_equal."""
        prev = {"amt": {"poc": 22500.0, "state": "BALANCED"}}
        curr = {"amt": {"poc": 22510.0, "state": "BALANCED"}}
        assert not _deep_equal(prev["amt"], curr["amt"])


class TestTickParsing:
    """Test tick parsing and validation."""

    def test_parse_valid_tick(self):
        """Valid tick dict → OHLC object."""
        raw = {
            "time": "2024-01-01T09:15:00",
            "open": 22500.0,
            "high": 22520.0,
            "low": 22490.0,
            "close": 22510.0,
            "volume": 1000.0,
            "vwap": 22505.0,
            "takerBuyVolume": 600.0,
            "delta": 200.0,
        }
        tick = _parse_tick(raw)
        assert isinstance(tick, OHLC)
        assert tick.open == 22500.0
        assert tick.close == 22510.0

    def test_parse_tick_missing_fields(self):
        """Missing fields → defaults to 0."""
        raw = {"time": "2024-01-01"}
        tick = _parse_tick(raw)
        assert tick.open == 0.0

    def test_validate_valid_tick(self):
        """Valid tick → no validation error."""
        tick = OHLC(
            time="2024-01-01", open=22500.0, high=22520.0,
            low=22490.0, close=22510.0, volume=1000.0,
            vwap=22505.0, taker_buy_volume=600.0, delta=200.0,
        )
        err = _validate_tick(tick)
        assert err is None

    def test_validate_high_less_than_low(self):
        """high < low → validation error."""
        tick = OHLC(
            time="2024-01-01", open=22500.0, high=22490.0,
            low=22520.0, close=22510.0, volume=1000.0,
            vwap=22505.0, taker_buy_volume=600.0, delta=200.0,
        )
        err = _validate_tick(tick)
        assert err is not None
        assert "high" in err.lower()

    def test_validate_negative_price(self):
        """Negative price → validation error."""
        tick = OHLC(
            time="2024-01-01", open=-100.0, high=22520.0,
            low=22490.0, close=22510.0, volume=1000.0,
            vwap=22505.0, taker_buy_volume=600.0, delta=200.0,
        )
        err = _validate_tick(tick)
        assert err is not None

    def test_validate_nan_price(self):
        """NaN price → validation error."""
        import math
        tick = OHLC(
            time="2024-01-01", open=float("nan"), high=22520.0,
            low=22490.0, close=22510.0, volume=1000.0,
            vwap=22505.0, taker_buy_volume=600.0, delta=200.0,
        )
        err = _validate_tick(tick)
        assert err is not None


class TestOrderBookParsing:
    """Test order book parsing."""

    def test_parse_valid_order_book(self):
        """Valid order book dict → OrderBook object."""
        raw = {
            "bids": [{"price": 22500.0, "quantity": 100}],
            "asks": [{"price": 22510.0, "quantity": 50}],
        }
        ob = _parse_order_book(raw)
        assert isinstance(ob, OrderBook)
        assert len(ob.bids) == 1
        assert ob.bids[0].price == 22500.0

    def test_parse_none_order_book(self):
        """None input → None output."""
        assert _parse_order_book(None) is None

    def test_parse_empty_order_book(self):
        """Empty dict → OrderBook with empty bids/asks or None."""
        ob = _parse_order_book({})
        # Empty dict results in None or empty OrderBook
        if ob is not None:
            assert ob.bids == ()
            assert ob.asks == ()


class TestStateSerialization:
    """Test state serialization/deserialization round-trip."""

    def test_state_to_json_and_back(self):
        """State dict → JSON → dict round-trip."""
        state = {
            "symbol": "NIFTY",
            "price": 22500.0,
            "position": {"side": "LONG", "entry": 22480.0},
            "amt": {"poc": 22500.0, "state": "BALANCED"},
        }
        json_str = json.dumps(state)
        restored = json.loads(json_str)

        assert restored["symbol"] == "NIFTY"
        assert restored["position"]["side"] == "LONG"
        assert restored["amt"]["poc"] == 22500.0

    def test_delta_serialization(self):
        """Delta dict serializes correctly."""
        delta = {"_symbol": "NIFTY", "_type": "delta", "price": 22510.0}
        json_str = json.dumps(delta)
        restored = json.loads(json_str)

        assert restored["_type"] == "delta"
        assert restored["price"] == 22510.0

    def test_complex_state_round_trip(self):
        """Complex nested state serializes and restores."""
        state = {
            "symbol": "NIFTY",
            "portfolio": {
                "equity": 100000.0,
                "positions": [
                    {"id": "pos-1", "side": "LONG", "entry": 22500.0, "size": 1.0},
                ],
            },
            "amt": {
                "poc": 22500.0,
                "vah": 22600.0,
                "val": 22400.0,
                "market_state": "BALANCED",
            },
            "candles": [
                {"open": 22500.0, "high": 22520.0, "low": 22490.0, "close": 22510.0},
            ],
        }
        json_str = json.dumps(state)
        restored = json.loads(json_str)

        assert restored["portfolio"]["equity"] == 100000.0
        assert len(restored["portfolio"]["positions"]) == 1
        assert restored["amt"]["market_state"] == "BALANCED"
