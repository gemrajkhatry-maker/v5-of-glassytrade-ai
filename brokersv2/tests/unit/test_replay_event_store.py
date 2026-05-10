"""
Tests for Replay Infrastructure - Event Store.

Tests cover:
- Append-only storage
- Sequence indexing
- Range queries
- Event type indexing
- Checksum verification
- Edge cases
"""

from datetime import datetime, timezone

import pytest

from brokersv2.replay.event_store import EventRecord, EventStore


class TestEventRecord:
    """Test EventRecord data model."""

    def test_create_record(self):
        """Create event record with all fields."""
        record = EventRecord(
            sequence=1,
            timestamp=datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc),
            event_type="tick",
            event_data=b"serialized_data",
            checksum="chk_1_15",
        )

        assert record.sequence == 1
        assert record.event_type == "tick"
        assert record.event_data == b"serialized_data"


class TestEventStore:
    """Test event store functionality."""

    def test_append_event(self):
        """Append event to store."""
        store = EventStore()
        seq = store.append(event_type="tick", event_data=b"data")

        assert seq == 1

    def test_append_increments_sequence(self):
        """Sequence numbers increment on append."""
        store = EventStore()

        seq1 = store.append(event_type="tick", event_data=b"data1")
        seq2 = store.append(event_type="tick", event_data=b"data2")
        seq3 = store.append(event_type="tick", event_data=b"data3")

        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

    def test_get_event_by_sequence(self):
        """Retrieve event by sequence number."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data")

        record = store.get_event(1)

        assert record is not None
        assert record.sequence == 1
        assert record.event_type == "tick"

    def test_get_nonexistent_event(self):
        """Returns None for nonexistent sequence."""
        store = EventStore()

        record = store.get_event(999)

        assert record is None

    def test_get_events_range(self):
        """Retrieve events in sequence range."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data1")
        store.append(event_type="depth", event_data=b"data2")
        store.append(event_type="tick", event_data=b"data3")

        events = store.get_events_range(1, 3)

        assert len(events) == 3
        assert events[0].sequence == 1
        assert events[1].sequence == 2
        assert events[2].sequence == 3

    def test_get_events_range_partial(self):
        """Range with gaps returns only existing events."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data1")
        store.append(event_type="tick", event_data=b"data2")

        events = store.get_events_range(1, 5)

        assert len(events) == 2

    def test_get_events_by_type(self):
        """Filter events by type."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"tick1")
        store.append(event_type="depth", event_data=b"depth1")
        store.append(event_type="tick", event_data=b"tick2")

        tick_events = store.get_events_by_type("tick")

        assert len(tick_events) == 2
        assert all(e.event_type == "tick" for e in tick_events)

    def test_get_events_by_type_empty(self):
        """Returns empty list for unknown type."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data")

        events = store.get_events_by_type("unknown")

        assert events == []

    def test_get_latest_sequence(self):
        """Get latest sequence number."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data1")
        store.append(event_type="tick", event_data=b"data2")

        latest = store.get_latest_sequence()

        assert latest == 2

    def test_get_latest_sequence_empty(self):
        """Returns 0 when store is empty."""
        store = EventStore()

        latest = store.get_latest_sequence()

        assert latest == 0

    def test_get_event_count(self):
        """Get total event count."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data1")
        store.append(event_type="tick", event_data=b"data2")
        store.append(event_type="tick", event_data=b"data3")

        assert store.get_event_count() == 3

    def test_len_operator(self):
        """Len operator returns event count."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data")

        assert len(store) == 1

    def test_clear_store(self):
        """Clear removes all events."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data1")
        store.append(event_type="tick", event_data=b"data2")
        store.clear()

        assert store.get_event_count() == 0
        assert store.get_latest_sequence() == 0

    def test_clear_allows_reuse(self):
        """Store can be reused after clear."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data1")
        store.clear()

        seq = store.append(event_type="tick", event_data=b"data2")

        assert seq == 1

    def test_verify_checksum_valid(self):
        """Verify checksum for valid event."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data")

        assert store.verify_checksum(1) is True

    def test_verify_checksum_legacy_format(self):
        """Verify checksum supports legacy format."""
        store = EventStore()
        # Manually insert a legacy-format record
        legacy_record = EventRecord(
            sequence=1,
            timestamp=datetime.now(timezone.utc),
            event_type="tick",
            event_data=b"data",
            checksum="chk_1_4",
        )
        store._events[1] = legacy_record
        store._next_sequence = 2

        assert store.verify_checksum(1) is True

    def test_verify_checksum_invalid(self):
        """Verify checksum returns False for nonexistent."""
        store = EventStore()

        assert store.verify_checksum(999) is False

    def test_append_with_custom_timestamp(self):
        """Append event with custom timestamp."""
        store = EventStore()
        ts = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)

        store.append(event_type="tick", event_data=b"data", timestamp=ts)

        record = store.get_event(1)
        assert record.timestamp == ts

    def test_append_auto_timestamp(self):
        """Append event with auto-generated timestamp."""
        store = EventStore()
        before = datetime.now(timezone.utc)

        store.append(event_type="tick", event_data=b"data")

        after = datetime.now(timezone.utc)
        record = store.get_event(1)

        assert before <= record.timestamp <= after

    def test_store_multiple_event_types(self):
        """Store handles multiple event types correctly."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"tick")
        store.append(event_type="depth", event_data=b"depth")
        store.append(event_type="candle", event_data=b"candle")

        assert store.get_event_count() == 3
        assert len(store.get_events_by_type("tick")) == 1
        assert len(store.get_events_by_type("depth")) == 1
        assert len(store.get_events_by_type("candle")) == 1

    def test_checksum_detects_tampering(self):
        """SHA256 checksum detects data tampering."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data")

        record = store.get_event(1)
        # Valid checksum should verify
        assert store.verify_checksum(1) is True

        # Tamper with the data
        original_data = record.event_data
        record.event_data = b"tampered"
        assert store.verify_checksum(1) is False

        # Restore original data
        record.event_data = original_data
        assert store.verify_checksum(1) is True

    def test_checksum_same_data_same_hash(self):
        """Identical data produces identical SHA256 checksums."""
        store = EventStore()
        store.append(event_type="tick", event_data=b"data")
        store.append(event_type="tick", event_data=b"data")

        record1 = store.get_event(1)
        record2 = store.get_event(2)

        # Same data should have same SHA256 checksum
        assert record1.checksum == record2.checksum
        assert record1.checksum.startswith("v1:sha256:")
