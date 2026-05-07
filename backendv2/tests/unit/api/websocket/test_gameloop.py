"""WebSocket game-loop handler tests."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.api.websocket.gameloop import (
    _safe_send,
    _deep_equal,
    _compute_delta,
    _parse_tick,
    _parse_order_book,
    _validate_tick,
)
from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel


class TestSafeSend:
    """Test _safe_send helper."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Should return True when send succeeds."""
        ws = MagicMock()
        ws.send_json = AsyncMock()
        result = await _safe_send(ws, {"key": "value"})
        assert result is True
        ws.send_json.assert_called_once_with({"key": "value"})

    @pytest.mark.asyncio
    async def test_send_disconnect(self):
        """Should return False when client disconnects."""
        from fastapi import WebSocketDisconnect
        ws = MagicMock()
        ws.send_json = AsyncMock(side_effect=WebSocketDisconnect())
        result = await _safe_send(ws, {"key": "value"})
        assert result is False

    @pytest.mark.asyncio
    async def test_send_runtime_error(self):
        """Should return False on runtime error."""
        ws = MagicMock()
        ws.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        result = await _safe_send(ws, {"key": "value"})
        assert result is False


class TestDeepEqual:
    """Test _deep_equal helper."""

    def test_equal_dicts(self):
        """Should return True for identical dicts."""
        assert _deep_equal({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) is True

    def test_different_dicts(self):
        """Should return False for different dicts."""
        assert _deep_equal({"a": 1}, {"a": 2}) is False

    def test_equal_lists(self):
        """Should return True for identical lists."""
        assert _deep_equal([1, 2, 3], [1, 2, 3]) is True

    def test_different_types(self):
        """Should return False for different types."""
        assert _deep_equal(1, "1") is False

    def test_equal_primitives(self):
        """Should return True for equal primitives."""
        assert _deep_equal(42, 42) is True
        assert _deep_equal("test", "test") is True


class TestComputeDelta:
    """Test _compute_delta helper."""

    def test_no_previous(self):
        """Should return full state when no previous state."""
        current = {"key": "value", "_meta": "data"}
        delta = _compute_delta(None, current)
        assert delta == current

    def test_no_changes(self):
        """Should return empty dict when nothing changed."""
        state = {"key": "value", "_meta": "data"}
        delta = _compute_delta(state, state)
        assert delta == {}

    def test_partial_change(self):
        """Should return only changed keys."""
        prev = {"key1": "value1", "key2": "value2"}
        current = {"key1": "value1", "key2": "changed"}
        delta = _compute_delta(prev, current)
        assert "key1" not in delta
        assert delta.get("key2") == "changed"

    def test_new_key_added(self):
        """Should include new keys in delta."""
        prev = {"key1": "value1"}
        current = {"key1": "value1", "key2": "new"}
        delta = _compute_delta(prev, current)
        assert delta.get("key2") == "new"

    def test_meta_keys_excluded(self):
        """Should exclude keys starting with underscore from delta comparison."""
        prev = {"_meta": "old", "data": "value"}
        current = {"_meta": "new", "data": "value"}
        delta = _compute_delta(prev, current)
        assert delta == {}


class TestParseTick:
    """Test _parse_tick helper."""

    def test_parse_valid_tick(self):
        """Should parse valid tick dict to OHLC."""
        raw = {
            "time": "2026-01-01T10:00:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000,
            "vwap": 100.3,
            "takerBuyVolume": 600,
            "delta": 200,
        }
        tick = _parse_tick(raw)
        assert isinstance(tick, OHLC)
        assert tick.open == 100.0
        assert tick.high == 101.0
        assert tick.volume == 1000

    def test_parse_tick_defaults(self):
        """Should use defaults for missing fields."""
        raw = {}
        tick = _parse_tick(raw)
        assert tick.open == 0
        assert tick.high == 0
        assert tick.volume == 0


class TestParseOrderBook:
    """Test _parse_order_book helper."""

    def test_parse_valid_orderbook(self):
        """Should parse valid orderbook dict."""
        raw = {
            "bids": [{"price": 100.0, "quantity": 10}],
            "asks": [{"price": 101.0, "quantity": 5}],
        }
        ob = _parse_order_book(raw)
        assert isinstance(ob, OrderBook)
        assert len(ob.bids) == 1
        assert len(ob.asks) == 1
        assert ob.bids[0].price == 100.0

    def test_parse_none_returns_none(self):
        """Should return None for None input."""
        assert _parse_order_book(None) is None

    def test_parse_empty_returns_none(self):
        """Should return None for empty dict."""
        assert _parse_order_book({}) is None


class TestValidateTick:
    """Test _validate_tick helper."""

    def test_valid_tick(self):
        """Should return None for valid tick."""
        tick = OHLC.create(
            time="2026-01-01", open=100, high=101, low=99, close=100.5, volume=1000
        )
        assert _validate_tick(tick) is None

    def test_negative_price(self):
        """Should reject negative prices."""
        tick = OHLC.create(
            time="2026-01-01", open=-100, high=101, low=99, close=100.5, volume=1000
        )
        assert _validate_tick(tick) is not None

    def test_high_below_low(self):
        """Should reject when high < low."""
        tick = OHLC.create(
            time="2026-01-01", open=100, high=99, low=101, close=100.5, volume=1000
        )
        assert _validate_tick(tick) is not None

    def test_nan_price(self):
        """Should reject NaN prices."""
        tick = OHLC.create(
            time="2026-01-01", open=float('nan'), high=101, low=99, close=100.5, volume=1000
        )
        assert _validate_tick(tick) is not None

    def test_negative_volume(self):
        """Should reject negative volume."""
        tick = OHLC.create(
            time="2026-01-01", open=100, high=101, low=99, close=100.5, volume=-100
        )
        assert _validate_tick(tick) is not None

    def test_infinite_price(self):
        """Should reject infinite prices."""
        tick = OHLC.create(
            time="2026-01-01", open=float('inf'), high=101, low=99, close=100.5, volume=1000
        )
        assert _validate_tick(tick) is not None
