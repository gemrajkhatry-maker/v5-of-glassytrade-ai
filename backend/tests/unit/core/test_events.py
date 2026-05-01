"""Tests for events module."""

import pytest
import tempfile
import os
from app.core.events import Event, EventStore, publish_event


class TestEventStore:
    def test_save_and_query(self):
        """Test saving and querying events."""
        store = EventStore()  # Singleton, no args
        event = Event(
            event_type="test",
            correlation_id="test-123",
            timestamp="2026-01-01T00:00:00",
            component="test",
            symbol="TEST",
            phase="test",
            data={"key": "value"}
        )
        event_id = store.save(event)
        assert event_id > 0
        
        results = store.query(event_type="test")
        assert len(results) >= 1
        assert results[0].event_type == "test"

    def test_get_timeline(self):
        """Test timeline query by symbol."""
        store = EventStore()  # Singleton
        event = Event(
            event_type="test",
            correlation_id="test-123",
            timestamp="2026-01-01T00:00:00",
            component="test",
            symbol="TEST"
        )
        store.save(event)
        
        timeline = store.get_timeline("TEST")
        assert len(timeline) >= 1


class TestPublishEvent:
    """Test publish_event function."""
    
    def test_publish(self):
        """Test publishing an event returns event ID."""
        event_id = publish_event(
            "test_event",
            "test_component",
            symbol="TEST",
            data={"test": True}
        )
        assert isinstance(event_id, int)
        assert event_id > 0