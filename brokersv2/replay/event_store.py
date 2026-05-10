"""
Replay Infrastructure - Event Store.

Append-only event log storage with indexed access.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class EventRecord:
    """Event stored in event log."""
    sequence: int
    timestamp: datetime
    event_type: str
    event_data: bytes
    checksum: str


class EventStore:
    """
    Append-only event log storage.
    
    Features:
    - Sequential event storage
    - Indexed by sequence number
    - Range queries (seq_start, seq_end)
    - Metadata indexing
    - Compression support
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize event store.
        
        Args:
            storage_path: Path for event log (default: in-memory)
        """
        self._storage_path = storage_path
        self._events: Dict[int, EventRecord] = {}
        self._next_sequence = 1
        self._event_types: Dict[str, List[int]] = {}
    
    def append(self, event_type: str, event_data: bytes, timestamp: Optional[datetime] = None) -> int:
        """
        Append event to store.
        
        Args:
            event_type: Event type identifier
            event_data: Serialized event data
            timestamp: Event timestamp (default: now)
        
        Returns:
            Sequence number assigned
        """
        seq = self._next_sequence
        timestamp = timestamp or datetime.now(timezone.utc)
        checksum = self._compute_checksum(seq, event_data)
        
        record = EventRecord(
            sequence=seq,
            timestamp=timestamp,
            event_type=event_type,
            event_data=event_data,
            checksum=checksum,
        )
        
        self._events[seq] = record
        self._event_types.setdefault(event_type, []).append(seq)
        self._next_sequence += 1
        
        return seq
    
    def get_event(self, sequence: int) -> Optional[EventRecord]:
        """Get event by sequence number."""
        return self._events.get(sequence)
    
    def get_events_range(self, seq_start: int, seq_end: int) -> List[EventRecord]:
        """
        Get events in sequence range (inclusive).
        
        Args:
            seq_start: Start sequence
            seq_end: End sequence
        
        Returns:
            List of events in range
        """
        events = []
        for seq in range(seq_start, seq_end + 1):
            if seq in self._events:
                events.append(self._events[seq])
        return events
    
    def get_events_by_type(self, event_type: str) -> List[EventRecord]:
        """Get all events of specific type."""
        sequences = self._event_types.get(event_type, [])
        return [self._events[seq] for seq in sequences if seq in self._events]
    
    def get_latest_sequence(self) -> int:
        """Get latest sequence number."""
        return self._next_sequence - 1
    
    def get_event_count(self) -> int:
        """Get total event count."""
        return len(self._events)
    
    def clear(self) -> None:
        """Clear all events."""
        self._events.clear()
        self._event_types.clear()
        self._next_sequence = 1
    
    def verify_checksum(self, sequence: int) -> bool:
        """Verify event checksum.

        Supports both legacy (chk_) and new (v1:sha256:) checksum formats.
        """
        record = self._events.get(sequence)
        if not record:
            return False

        stored = record.checksum
        if stored.startswith("v1:sha256:"):
            expected = self._compute_checksum_sha256(sequence, data=record.event_data)
            return stored == expected
        elif stored.startswith("chk_"):
            # Legacy format — fall back to length-based checksum
            expected = self._compute_checksum_legacy(sequence, record.event_data)
            return stored == expected
        return False

    def _compute_checksum(self, sequence: int, data: bytes) -> str:
        """Compute cryptographically secure SHA256 checksum for integrity."""
        return self._compute_checksum_sha256(sequence, data)

    def _compute_checksum_sha256(self, sequence: int, data: bytes) -> str:
        """Compute versioned SHA256 checksum.

        Format: v1:sha256:<hexdigest>
        """
        digest = hashlib.sha256(data).hexdigest()
        return f"v1:sha256:{digest}"

    def _compute_checksum_legacy(self, sequence: int, data: bytes) -> str:
        """Legacy length-based checksum (for backward compatibility)."""
        return f"chk_{sequence}_{len(data)}"
    
    def __len__(self) -> int:
        return len(self._events)
