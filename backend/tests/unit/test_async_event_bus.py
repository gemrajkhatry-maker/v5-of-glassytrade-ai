"""Unit tests for AsyncEventBus.

Tests the async event-driven architecture implementation.
"""

import pytest
import asyncio
from unittest.mock import MagicMock
from app.infrastructure.async_event_bus import AsyncEventBus


# Mock DomainEvent for testing
class MockEvent:
    """Mock domain event for testing."""
    def __init__(self, data: str = "test"):
        self.data = data


class TestAsyncEventBus:
    """Test suite for AsyncEventBus."""

    def test_initial_state(self):
        """New bus should have no subscribers."""
        bus = AsyncEventBus()
        assert bus.subscriber_count == 0
        assert bus.event_count == 0
        assert bus.error_count == 0

    def test_subscribe_sync_handler(self):
        """Should subscribe sync handlers."""
        bus = AsyncEventBus()
        handler = MagicMock()
        bus.subscribe(MockEvent, handler)
        assert bus.subscriber_count == 1

    def test_subscribe_async_handler(self):
        """Should subscribe async handlers."""
        bus = AsyncEventBus()
        async def handler(event):
            pass
        bus.subscribe(MockEvent, handler)
        assert bus.subscriber_count == 1

    @pytest.mark.asyncio
    async def test_publish_calls_handler(self):
        """Publish should call subscribed handler."""
        bus = AsyncEventBus()
        handler = MagicMock()
        bus.subscribe(MockEvent, handler)

        event = MockEvent(data="hello")
        await bus.publish(event)

        handler.assert_called_once_with(event)
        assert bus.event_count == 1

    @pytest.mark.asyncio
    async def test_publish_multiple_handlers(self):
        """Publish should call all subscribed handlers."""
        bus = AsyncEventBus()
        handler1 = MagicMock()
        handler2 = MagicMock()
        bus.subscribe(MockEvent, handler1)
        bus.subscribe(MockEvent, handler2)

        event = MockEvent(data="hello")
        await bus.publish(event)

        handler1.assert_called_once_with(event)
        handler2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_handler_error_does_not_block_others(self):
        """Handler error should not block other handlers."""
        bus = AsyncEventBus()
        
        def failing_handler(event):
            raise ValueError("Test error")
        
        success_handler = MagicMock()
        bus.subscribe(MockEvent, failing_handler)
        bus.subscribe(MockEvent, success_handler)

        event = MockEvent(data="hello")
        await bus.publish(event)

        # Success handler should still be called
        success_handler.assert_called_once_with(event)
        assert bus.error_count == 1

    def test_clear_removes_all_subscribers(self):
        """Clear should remove all subscribers."""
        bus = AsyncEventBus()
        bus.subscribe(MockEvent, MagicMock())
        bus.subscribe(MockEvent, MagicMock())
        assert bus.subscriber_count == 2

        bus.clear()
        assert bus.subscriber_count == 0


class TestPositionEventSourcing:
    """Test suite for PositionEventSourcingService."""

    def _create_service(self):
        """Create a PositionEventSourcingService with mock storage."""
        from app.application.services.position_event_sourcing import PositionEventSourcingService
        storage = MagicMock()
        storage.save_position_event = MagicMock()
        return PositionEventSourcingService(storage=storage), storage

    def test_record_opened(self):
        """Should record position opened event."""
        service, storage = self._create_service()
        event = service.record_opened(
            position_id="pos_123",
            symbol="CRUDEOIL",
            side="LONG",
            entry_price=6100.0,
            stop_loss=6050.0,
            take_profit=6200.0,
        )
        assert event.event_type == "OPENED"
        assert event.position_id == "pos_123"
        assert service.get_event_count() == 1
        storage.save_position_event.assert_called_once()

    def test_record_closed(self):
        """Should record position closed event."""
        service, _ = self._create_service()
        event = service.record_closed(
            position_id="pos_123",
            symbol="CRUDEOIL",
            side="LONG",
            entry_price=6100.0,
            exit_price=6200.0,
            pnl=1000.0,
            exit_reason="TARGET",
        )
        assert event.event_type == "CLOSED"
        assert event.data["pnl"] == 1000.0
        assert service.get_event_count() == 1

    def test_record_partial_exit(self):
        """Should record partial exit event."""
        service, _ = self._create_service()
        event = service.record_partial_exit(
            position_id="pos_123",
            symbol="CRUDEOIL",
            exit_pct=0.30,
            exit_price=6150.0,
            realized_pnl=500.0,
            reason="Seed recovery — weak momentum",
        )
        assert event.event_type == "PARTIAL_EXIT"
        assert event.data["exit_pct"] == 0.30

    def test_record_stop_loss_moved(self):
        """Should record stop loss moved event."""
        service, _ = self._create_service()
        event = service.record_stop_loss_moved(
            position_id="pos_123",
            symbol="CRUDEOIL",
            old_sl=6050.0,
            new_sl=6100.0,
            reason="Breakeven moved at 1R",
        )
        assert event.event_type == "STOP_LOSS_MOVED"
        assert event.data["old_sl"] == 6050.0
        assert event.data["new_sl"] == 6100.0

    def test_get_events_for_position(self):
        """Should return events for a specific position."""
        service, _ = self._create_service()
        service.record_opened("pos_1", "CRUDEOIL", "LONG", 6100, 6050, 6200)
        service.record_opened("pos_2", "GOLD", "SHORT", 61000, 61500, 60000)
        service.record_closed("pos_1", "CRUDEOIL", "LONG", 6100, 6200, 1000, "TARGET")

        events = service.get_events_for_position("pos_1")
        assert len(events) == 2
        assert events[0].event_type == "OPENED"
        assert events[1].event_type == "CLOSED"

    def test_get_events_for_symbol(self):
        """Should return events for a specific symbol."""
        service, _ = self._create_service()
        service.record_opened("pos_1", "CRUDEOIL", "LONG", 6100, 6050, 6200)
        service.record_opened("pos_2", "GOLD", "SHORT", 61000, 61500, 60000)

        events = service.get_events_for_symbol("CRUDEOIL")
        assert len(events) == 1
        assert events[0].data["symbol"] == "CRUDEOIL"

    def test_clear(self):
        """Clear should remove all events."""
        service, _ = self._create_service()
        service.record_opened("pos_1", "CRUDEOIL", "LONG", 6100, 6050, 6200)
        assert service.get_event_count() == 1

        service.clear()
        assert service.get_event_count() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])