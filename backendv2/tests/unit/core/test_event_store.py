"""Tests for EventStore — immutable event timeline for diagnostics and audits.

Behavior: EventStore appends events immutably, supports filtering by type,
and provides read-only snapshots.
"""
from __future__ import annotations

import pytest

from app.core.event_store import Event, EventStore


class TestEvent:
    """Tests for Event value object."""

    def test_event_is_immutable(self):
        """Event should be frozen (immutable)."""
        event = Event(event_type="TICK", timestamp=1234567890.0, data={"price": 50000})
        
        with pytest.raises(AttributeError):
            event.event_type = "SIGNAL"  # type: ignore

    def test_event_has_unique_id(self):
        """Each event should have a unique ID."""
        event1 = Event(event_type="TICK", timestamp=1.0, data={})
        event2 = Event(event_type="TICK", timestamp=2.0, data={})
        
        assert event1.event_id != event2.event_id

    def test_event_auto_generates_timestamp(self):
        """Event should auto-generate timestamp if not provided."""
        import time
        before = time.time()
        event = Event(event_type="TICK", data={})
        after = time.time()
        
        assert before <= event.timestamp <= after


class TestEventStore:
    """Tests for EventStore behavior through public interface."""

    def test_appends_and_tracks_events(self):
        """EventStore should store and track events."""
        store = EventStore()
        
        store.append(Event(event_type="TICK", timestamp=1234567890.0, data={"price": 50000}))
        store.append(Event(event_type="SIGNAL", timestamp=1234567891.0, data={"type": "LONG"}))
        
        events = store.read_all()
        assert len(events) == 2

    def test_filters_by_event_type(self):
        """Should be able to filter events by type."""
        store = EventStore()
        store.append(Event(event_type="TICK", timestamp=1.0, data={}))
        store.append(Event(event_type="SIGNAL", timestamp=2.0, data={}))
        store.append(Event(event_type="TICK", timestamp=3.0, data={}))
        
        ticks = store.get_events("TICK")
        assert len(ticks) == 2
        assert all(e.event_type == "TICK" for e in ticks)

    def test_returns_all_events_when_no_filter(self):
        """Should return all events when no type filter provided."""
        store = EventStore()
        store.append(Event(event_type="TICK", timestamp=1.0, data={}))
        store.append(Event(event_type="SIGNAL", timestamp=2.0, data={}))
        
        events = store.get_events()
        assert len(events) == 2

    def test_returns_copy_not_reference(self):
        """Should return a copy to prevent external mutation."""
        store = EventStore()
        store.append(Event(event_type="TICK", timestamp=1.0, data={}))
        
        events = store.read_all()
        events.clear()  # Try to mutate the returned list
        
        # Original store should be unaffected
        assert len(store.read_all()) == 1

    def test_snapshot_is_read_only_alias(self):
        """Snapshot should be equivalent to read_all."""
        store = EventStore()
        store.append(Event(event_type="TICK", timestamp=1.0, data={}))
        
        snapshot = store.snapshot()
        assert len(snapshot) == 1
        assert snapshot == store.read_all()

    def test_empty_store_returns_empty_list(self):
        """Empty store should return empty list."""
        store = EventStore()
        
        assert store.read_all() == []
        assert store.get_events() == []
        assert store.get_events("TICK") == []

    def test_filters_nonexistent_type(self):
        """Filtering by non-existent type should return empty list."""
        store = EventStore()
        store.append(Event(event_type="TICK", timestamp=1.0, data={}))
        
        result = store.get_events("NONEXISTENT")
        assert result == []

    def test_preserves_insertion_order(self):
        """Events should be returned in insertion order."""
        store = EventStore()
        store.append(Event(event_type="FIRST", timestamp=1.0, data={}))
        store.append(Event(event_type="SECOND", timestamp=2.0, data={}))
        store.append(Event(event_type="THIRD", timestamp=3.0, data={}))
        
        events = store.read_all()
        assert events[0].event_type == "FIRST"
        assert events[1].event_type == "SECOND"
        assert events[2].event_type == "THIRD"

    def test_stores_complex_data(self):
        """Should handle complex nested data in events."""
        complex_data = {
            "symbol": "NIFTY",
            "price": 23500.50,
            "indicators": {
                "vwap": 23480.0,
                "atr": 45.2
            },
            "levels": [23400.0, 23500.0, 23600.0]
        }
        
        store = EventStore()
        store.append(Event(event_type="AMT_ANALYSIS", timestamp=1.0, data=complex_data))
        
        events = store.read_all()
        assert events[0].data["symbol"] == "NIFTY"
        assert events[0].data["indicators"]["vwap"] == 23480.0
        assert len(events[0].data["levels"]) == 3
