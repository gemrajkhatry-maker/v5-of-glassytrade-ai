"""Tests for event store and event architecture."""

import pytest
from datetime import datetime, timezone

from app.domain.trading.events import (
    DomainEvent,
    FillReceived,
    SignalGenerated,
    PositionChanged,
    OrderPlaced,
)
from app.domain.trading.event_store import (
    InMemoryEventStore,
    EventBus,
    EventSystem,
    AuditTrailVerifier,
    DuplicateEventError,
)


class TestInMemoryEventStore:
    """Tests for InMemoryEventStore."""

    def test_append_single_event(self):
        """Can append a single event."""
        store = InMemoryEventStore()
        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            order_id="O1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )
        store.append(event)
        assert store.get_event_count() == 1

    def test_append_multiple_events(self):
        """Can append multiple events."""
        store = InMemoryEventStore()

        event1 = SignalGenerated(
            idempotency_key="sig1",
            signal_id="S1",
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            confidence="HIGH",
            setup_type="TREND",
        )

        event2 = FillReceived(
            idempotency_key="fill1",
            trade_id="T1",
            fill_id="F1",
            order_id="O1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        store.append(event1)
        store.append(event2)

        assert store.get_event_count() == 2

    def test_duplicate_event_raises_error(self):
        """Duplicate idempotency key raises error."""
        store = InMemoryEventStore()

        event = FillReceived(
            idempotency_key="dup_key",
            trade_id="T1",
            fill_id="F1",
            order_id="O1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        store.append(event)

        with pytest.raises(DuplicateEventError):
            store.append(event)

    def test_get_events_by_aggregate(self):
        """Can query events by trade_id."""
        store = InMemoryEventStore()

        # Add events for different trades
        event1 = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )
        event2 = FillReceived(
            trade_id="T2",
            fill_id="F2",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=50.0,
        )
        event3 = FillReceived(
            trade_id="T1",
            fill_id="F3",
            symbol="NIFTY",
            side="SELL",
            fill_type="EXIT",
            price=120.0,
            quantity=75.0,
        )

        store.append(event1)
        store.append(event2)
        store.append(event3)

        # Query by trade T1
        t1_events = store.get_events(aggregate_id="T1")
        assert len(t1_events) == 2

        # Query by trade T2
        t2_events = store.get_events(aggregate_id="T2")
        assert len(t2_events) == 1

    def test_get_events_by_type(self):
        """Can query events by event type."""
        store = InMemoryEventStore()

        event1 = SignalGenerated(
            signal_id="S1",
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            confidence="HIGH",
            setup_type="TREND",
        )
        event2 = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        store.append(event1)
        store.append(event2)

        signals = store.get_events(event_type="SignalGenerated")
        fills = store.get_events(event_type="FillReceived")

        assert len(signals) == 1
        assert len(fills) == 1

    def test_clear_events(self):
        """Can clear all events."""
        store = InMemoryEventStore()

        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )
        store.append(event)

        assert store.get_event_count() == 1

        store.clear()

        assert store.get_event_count() == 0


class TestEventBus:
    """Tests for EventBus."""

    def test_subscribe_and_publish(self):
        """Can subscribe to events and receive them."""
        bus = EventBus()
        received = []

        def handler(event: DomainEvent):
            received.append(event)

        bus.subscribe("FillReceived", handler)

        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )
        bus.publish(event)

        assert len(received) == 1
        assert received[0].trade_id == "T1"

    def test_publish_to_store(self):
        """Events are persisted to event store."""
        system = EventSystem("memory")
        store = system.event_store  # Get store first so bus can reference it
        bus = system.event_bus

        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )
        bus.publish(event)

        assert store.get_event_count() == 1

    def test_duplicate_events_skipped(self):
        """Duplicate events are logged but handlers are still notified.

        Note: The current implementation notifies handlers for all published events,
        but skips persistence of duplicates. This is by design - handlers
        may need to see duplicate notifications for reconciliation.
        """
        system = EventSystem("memory")
        store = system.event_store  # Get store first so bus can reference it
        bus = system.event_bus

        received_count = []

        def handler(event: DomainEvent):
            received_count.append(1)

        bus.subscribe("FillReceived", handler)

        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        bus.publish(event)
        bus.publish(event)  # Duplicate - handlers NOT notified (true idempotency)

        # True idempotency: handlers notified only for NEW events
        assert len(received_count) == 1
        assert store.get_event_count() == 1

    def test_event_system_isolation(self):
        """Each EventSystem instance has isolated bus and store."""
        system1 = EventSystem("memory")
        system2 = EventSystem("memory")
        assert system1.event_bus is not system2.event_bus
        assert system1.event_store is not system2.event_store


class TestAuditTrailVerifier:
    """Tests for AuditTrailVerifier."""

    def test_verify_events(self):
        """Can verify events to reconstruct state."""
        store = InMemoryEventStore()
        verifier = AuditTrailVerifier(store)

        # Add events
        signal = SignalGenerated(
            signal_id="S1",
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            confidence="HIGH",
            setup_type="TREND",
        )
        fill = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        store.append(signal)
        store.append(fill)

        # Verify
        state = verifier.verify_to(aggregate_id="T1")

        assert len(state["events"]) == 1  # Only T1 events

    def test_verify_determinism(self):
        """Can verify deterministic verification."""
        store = InMemoryEventStore()
        verifier = AuditTrailVerifier(store)

        events = [
            SignalGenerated(
                signal_id="S1",
                symbol="NIFTY",
                direction="LONG",
                entry_price=100.0,
                stop_loss=95.0,
                take_profit=115.0,
                position_size=75.0,
                confidence="HIGH",
                setup_type="TREND",
            ),
        ]

        # Add events to store
        for e in events:
            store.append(e)

        # Verify determinism
        assert verifier.verify_determinism(events) is True


class TestEventIdempotency:
    """Tests for event idempotency."""

    def test_idempotency_key_generated(self):
        """Events have idempotency keys."""
        event = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        assert event.idempotency_key is not None
        assert len(event.idempotency_key) > 0

    def test_custom_idempotency_key(self):
        """Can provide custom idempotency key."""
        event = FillReceived(
            idempotency_key="custom_key",
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        assert event.idempotency_key == "custom_key"


class TestEventOrdering:
    """Tests for event timestamp ordering."""

    def test_events_ordered_by_timestamp(self):
        """Events are ordered by timestamp."""
        store = InMemoryEventStore()

        # Create events with different timestamps
        event1 = FillReceived(
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )
        event1 = FillReceived(
            event_id="e1",
            idempotency_key="e1",
            timestamp="2025-01-01T10:00:00Z",
            trade_id="T1",
            fill_id="F1",
            symbol="NIFTY",
            side="BUY",
            fill_type="ENTRY",
            price=100.0,
            quantity=75.0,
        )

        event2 = FillReceived(
            event_id="e2",
            idempotency_key="e2",
            timestamp="2025-01-01T10:01:00Z",
            trade_id="T1",
            fill_id="F2",
            symbol="NIFTY",
            side="SELL",
            fill_type="EXIT",
            price=110.0,
            quantity=75.0,
        )

        store.append(event1)
        store.append(event2)

        events = store.get_events(aggregate_id="T1")

        assert events[0].timestamp < events[1].timestamp
