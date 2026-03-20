"""Unit tests for infrastructure components — event bus, data generator."""

import pytest
from app.domain.trading.events import DomainEvent, TickReceived, PositionClosed
from app.domain.trading.models.value_objects import OHLC
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.adapters.data_generator import generate_market_data


# ---------------------------------------------------------------------------
# InMemoryEventBus
# ---------------------------------------------------------------------------

class TestInMemoryEventBus:
    def test_publish_subscribe(self):
        bus = InMemoryEventBus()
        received = []
        bus.subscribe(TickReceived, lambda e: received.append(e))
        tick = OHLC(time="t", open=1, high=2, low=0.5, close=1.5, volume=100, vwap=1.3)
        bus.publish(TickReceived(symbol="BTCUSDT", tick=tick))
        assert len(received) == 1
        assert received[0].symbol == "BTCUSDT"

    def test_multiple_handlers(self):
        bus = InMemoryEventBus()
        calls = {"a": 0, "b": 0}
        bus.subscribe(TickReceived, lambda e: calls.__setitem__("a", calls["a"] + 1))
        bus.subscribe(TickReceived, lambda e: calls.__setitem__("b", calls["b"] + 1))
        tick = OHLC(time="t", open=1, high=2, low=0.5, close=1.5, volume=100, vwap=1.3)
        bus.publish(TickReceived(symbol="S", tick=tick))
        assert calls["a"] == 1
        assert calls["b"] == 1

    def test_unrelated_event_not_received(self):
        bus = InMemoryEventBus()
        received = []
        bus.subscribe(PositionClosed, lambda e: received.append(e))
        tick = OHLC(time="t", open=1, high=2, low=0.5, close=1.5, volume=100, vwap=1.3)
        bus.publish(TickReceived(symbol="S", tick=tick))
        assert len(received) == 0

    def test_handler_error_does_not_break_others(self):
        bus = InMemoryEventBus()
        second_called = []

        def bad_handler(e):
            raise RuntimeError("boom")

        bus.subscribe(TickReceived, bad_handler)
        bus.subscribe(TickReceived, lambda e: second_called.append(True))
        tick = OHLC(time="t", open=1, high=2, low=0.5, close=1.5, volume=100, vwap=1.3)
        bus.publish(TickReceived(symbol="S", tick=tick))
        assert len(second_called) == 1

    def test_clear(self):
        bus = InMemoryEventBus()
        received = []
        bus.subscribe(TickReceived, lambda e: received.append(e))
        bus.clear()
        tick = OHLC(time="t", open=1, high=2, low=0.5, close=1.5, volume=100, vwap=1.3)
        bus.publish(TickReceived(symbol="S", tick=tick))
        assert len(received) == 0


# ---------------------------------------------------------------------------
# Data Generator
# ---------------------------------------------------------------------------

class TestDataGenerator:
    def test_default_generates_50(self):
        data = generate_market_data()
        assert len(data) == 50

    def test_custom_count(self):
        data = generate_market_data(days=10)
        assert len(data) == 10

    def test_returns_ohlc_objects(self):
        data = generate_market_data(5)
        for d in data:
            assert isinstance(d, OHLC)
            assert d.high >= d.low
            assert d.volume > 0

    def test_trend_bullish(self):
        data = generate_market_data(100, 100, "bullish")
        assert data[-1].close > data[0].close * 0.8  # should trend up

    def test_trend_bearish(self):
        data = generate_market_data(100, 100, "bearish")
        assert data[-1].close < data[0].close * 1.2  # should trend down

    def test_vwap_reasonable(self):
        data = generate_market_data(10)
        for d in data:
            assert d.low <= d.vwap * 1.1  # vwap should be in range
