"""Tests for Event Bus."""

import pytest
from brokersv2.events import EventBus, TickEvent, OrderEvent


class TestEventBus:
    """Tests for EventBus."""

    @pytest.mark.asyncio
    async def test_publish_and_receive(self):
        """Test basic event publishing."""
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(TickEvent, handler)
        await bus.publish(TickEvent(symbol="NSE:RELIANCE", price=100.0, volume=100))
        
        assert len(received) == 1
        assert received[0].symbol == "NSE:RELIANCE"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Test multiple handlers for same event type."""
        bus = EventBus()
        results = []

        async def handler1(event):
            results.append(("h1", event))

        async def handler2(event):
            results.append(("h2", event))

        bus.subscribe(TickEvent, handler1)
        bus.subscribe(TickEvent, handler2)
        await bus.publish(TickEvent(symbol="NSE:RELIANCE", price=100.0, volume=100))
        
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_dead_letter_queue(self):
        """Test that failed handlers go to dead-letter queue."""
        bus = EventBus()

        async def bad_handler(event):
            raise ValueError("Test error")

        bus.subscribe(TickEvent, bad_handler)
        await bus.publish(TickEvent(symbol="NSE:RELIANCE", price=100.0, volume=100))
        
        assert bus.get_dlq_size() == 1