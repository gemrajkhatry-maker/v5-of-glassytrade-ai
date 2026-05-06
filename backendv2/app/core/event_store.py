"""EventStore — in-memory immutable event timeline for diagnostics and audits.

Extracted from core_components.py to enable dependency injection and testing.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    """Immutable event record for audit trail.
    
    Attributes:
        event_type: Type identifier (e.g., "TICK", "SIGNAL", "POSITION_CLOSED")
        timestamp: Unix timestamp of event occurrence
        data: Event payload (arbitrary dict)
        event_id: Unique identifier (auto-generated UUID)
    """
    event_type: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class EventStore:
    """In-memory immutable event timeline for diagnostics and audits.
    
    Thread-unsafe by design (assumes single-threaded access or external sync).
    Returns copies to prevent external mutation.
    """
    
    def __init__(self):
        self._events: list[Event] = []
    
    def append(self, event: Event) -> None:
        """Append an event to the timeline."""
        self._events.append(event)
    
    def get_events(self, event_type: str | None = None) -> list[Event]:
        """Get events, optionally filtered by type.
        
        Args:
            event_type: Filter by event type (None for all events)
            
        Returns:
            Copy of matching events (prevents external mutation)
        """
        if event_type:
            return [e for e in self._events if e.event_type == event_type]
        return self._events.copy()
    
    def read_all(self) -> list[Event]:
        """Read all recorded events.
        
        Returns:
            Copy of all events (prevents external mutation)
        """
        return self._events.copy()

    def snapshot(self) -> list[Event]:
        """Alias for read-only timeline snapshots.
        
        Returns:
            Copy of all events
        """
        return self._events.copy()
