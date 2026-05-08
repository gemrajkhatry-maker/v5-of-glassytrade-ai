"""
Tests for Replay Infrastructure - Event Capture Engine.

Tests cover:
- Event capture lifecycle
- Sequence numbering
- Serialization
- Multiple concurrent captures
- Error conditions
"""

from datetime import datetime, timezone

import pytest

from brokersv2.replay.event_capture import CapturedEvent, EventCaptureEngine


class TestCapturedEvent:
    """Test CapturedEvent data model."""

    def test_create_captured_event(self):
        """Create event with required fields."""
        event = CapturedEvent(
            sequence=1,
            timestamp=datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc),
            event_type="tick",
            event_data={"symbol": "RELIANCE", "price": 2500.0},
        )

        assert event.sequence == 1
        assert event.event_type == "tick"
        assert event.event_data["symbol"] == "RELIANCE"

    def test_captured_event_with_metadata(self):
        """Create event with optional metadata."""
        event = CapturedEvent(
            sequence=2,
            timestamp=datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc),
            event_type="depth",
            event_data={"symbol": "TCS"},
            metadata={"source": "websocket", "latency_ms": 5},
        )

        assert event.metadata["source"] == "websocket"


class TestEventCaptureEngine:
    """Test event capture functionality."""

    def test_start_capture(self):
        """Start capturing events."""
        engine = EventCaptureEngine()
        engine.start_capture()

        # Should not raise
        event = engine.capture_event(
            event={"price": 100},
            event_type="tick",
        )

        assert event.sequence == 1

    def test_stop_capture(self):
        """Stop capturing events."""
        engine = EventCaptureEngine()
        engine.start_capture()
        engine.stop_capture()

        with pytest.raises(RuntimeError, match="Capture not started"):
            engine.capture_event(event={"price": 100}, event_type="tick")

    def test_capture_without_start_raises(self):
        """Cannot capture without starting."""
        engine = EventCaptureEngine()

        with pytest.raises(RuntimeError, match="Capture not started"):
            engine.capture_event(event={"price": 100}, event_type="tick")

    def test_sequence_numbers_increment(self):
        """Sequence numbers increment correctly."""
        engine = EventCaptureEngine()
        engine.start_capture()

        event1 = engine.capture_event(event={"price": 100}, event_type="tick")
        event2 = engine.capture_event(event={"price": 101}, event_type="tick")
        event3 = engine.capture_event(event={"price": 102}, event_type="tick")

        assert event1.sequence == 1
        assert event2.sequence == 2
        assert event3.sequence == 3

    def test_capture_event_type(self):
        """Event type is preserved."""
        engine = EventCaptureEngine()
        engine.start_capture()

        event = engine.capture_event(
            event={"bid": 100, "ask": 101},
            event_type="depth",
        )

        assert event.event_type == "depth"

    def test_capture_event_data(self):
        """Event data is extracted correctly."""
        engine = EventCaptureEngine()
        engine.start_capture()

        class MockEvent:
            def __init__(self):
                self.symbol = "RELIANCE"
                self.price = 2500.0

        event = engine.capture_event(
            event=MockEvent(),
            event_type="tick",
        )

        assert event.event_data["symbol"] == "RELIANCE"
        assert event.event_data["price"] == 2500.0

    def test_capture_with_metadata(self):
        """Metadata is attached to captured event."""
        engine = EventCaptureEngine()
        engine.start_capture()

        event = engine.capture_event(
            event={"price": 100},
            event_type="tick",
            metadata={"source": "test"},
        )

        assert event.metadata["source"] == "test"

    def test_get_captured_events(self):
        """Retrieve all captured events."""
        engine = EventCaptureEngine()
        engine.start_capture()

        engine.capture_event(event={"price": 100}, event_type="tick")
        engine.capture_event(event={"price": 101}, event_type="tick")

        events = engine.get_captured_events()

        assert len(events) == 2
        assert events[0].sequence == 1
        assert events[1].sequence == 2

    def test_get_captured_events_returns_copy(self):
        """Returned list is a copy, not internal state."""
        engine = EventCaptureEngine()
        engine.start_capture()

        engine.capture_event(event={"price": 100}, event_type="tick")
        events = engine.get_captured_events()
        events.clear()

        # Internal state should not be affected
        assert len(engine.get_captured_events()) == 1

    def test_clear_resets_state(self):
        """Clear removes all events and resets sequence."""
        engine = EventCaptureEngine()
        engine.start_capture()

        engine.capture_event(event={"price": 100}, event_type="tick")
        engine.capture_event(event={"price": 101}, event_type="tick")
        engine.clear()

        assert len(engine.get_captured_events()) == 0

        # Capture again should start from sequence 1
        event = engine.capture_event(event={"price": 102}, event_type="tick")
        assert event.sequence == 1

    def test_capture_timestamps(self):
        """Captured events have timestamps."""
        engine = EventCaptureEngine()
        engine.start_capture()

        before = datetime.now(timezone.utc)
        event = engine.capture_event(event={"price": 100}, event_type="tick")
        after = datetime.now(timezone.utc)

        assert before <= event.timestamp <= after

    def test_extract_primitive_data(self):
        """Extract data from primitive values."""
        engine = EventCaptureEngine()
        engine.start_capture()

        event = engine.capture_event(event=42, event_type="custom")

        assert event.event_data["value"] == "42"

    def test_extract_dict_data(self):
        """Extract data from dict directly."""
        engine = EventCaptureEngine()
        engine.start_capture()

        event = engine.capture_event(
            event={"key": "value"},
            event_type="custom",
        )

        assert event.event_data["key"] == "value"

    def test_multiple_capture_sessions(self):
        """Multiple start/stop cycles work correctly."""
        engine = EventCaptureEngine()

        # First session
        engine.start_capture()
        engine.capture_event(event={"price": 100}, event_type="tick")
        engine.stop_capture()

        # Second session
        engine.clear()
        engine.start_capture()
        event = engine.capture_event(event={"price": 200}, event_type="tick")

        assert event.sequence == 1
