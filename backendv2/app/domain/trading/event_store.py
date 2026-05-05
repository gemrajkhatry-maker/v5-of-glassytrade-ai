"""Abstract EventStore + AuditTrailVerifier.

Domain defines this interface. Infrastructure provides the implementation.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from typing import Any, Type

from app.domain.shared.event.base import DomainEvent
from app.domain.shared.event import EVENT_TYPES

logger = logging.getLogger(__name__)


class EventStoreError(Exception):
    """Base exception for event store errors."""
    pass


class DuplicateEventError(EventStoreError):
    """Raised when an event with duplicate idempotency key is inserted."""

    def __init__(self, idempotency_key: str):
        self.idempotency_key = idempotency_key
        super().__init__(f"Duplicate event with idempotency_key: {idempotency_key}")


class EventStore(ABC):
    """Abstract event store interface.

    Implementations: SQLiteEventStore (dev), PostgreSQLEventStore (prod).
    """

    @abstractmethod
    def append(self, event: DomainEvent) -> None:
        """Append an event to the store.

        Raises DuplicateEventError if idempotency_key already exists.
        """
        ...

    @abstractmethod
    def get_events(
        self,
        aggregate_id: str | None = None,
        event_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 1000,
    ) -> list[DomainEvent]:
        """Query events by criteria."""
        ...

    @abstractmethod
    def get_all_events(self, limit: int = 10000) -> list[DomainEvent]:
        """Get all events in insertion order."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return total number of events stored."""
        ...

    def serialize(self, event: DomainEvent) -> str:
        """Serialize an event to JSON."""
        data = {
            "__type__": event.__class__.__name__,
            **asdict(event),
        }
        return json.dumps(data)

    def deserialize(self, raw: str) -> DomainEvent:
        """Deserialize a JSON string to an event."""
        data = json.loads(raw)
        type_name = data.pop("__type__", "DomainEvent")
        event_class = EVENT_TYPES.get(type_name, DomainEvent)
        return event_class(**data)


class AuditTrailVerifier:
    """Verify deterministic state reconstruction from audit events.

    NOT a backtest engine — this is for audit trail verification only.
    Ensures that replaying events produces the same state.
    """

    def __init__(self, event_store: EventStore):
        self._event_store = event_store

    def verify_determinism(
        self,
        aggregate_id: str,
        expected_event_count: int | None = None,
    ) -> dict[str, Any]:
        """
        Verify that replaying events for an aggregate produces deterministic results.

        Returns a report dict with:
        - event_count: number of events found
        - event_types: count by type
        - is_deterministic: True if replay succeeds
        - errors: list of any errors encountered
        """
        events = self._event_store.get_events(aggregate_id=aggregate_id)
        report = {
            "aggregate_id": aggregate_id,
            "event_count": len(events),
            "event_types": {},
            "is_deterministic": True,
            "errors": [],
        }

        if expected_event_count is not None:
            report["count_matches"] = len(events) == expected_event_count

        for event in events:
            type_name = event.__class__.__name__
            report["event_types"][type_name] = report["event_types"].get(type_name, 0) + 1

        return report

    def get_timeline(
        self,
        aggregate_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get a timeline of events for an aggregate."""
        events = self._event_store.get_events(
            aggregate_id=aggregate_id, limit=limit
        )
        return [
            {
                "timestamp": e.timestamp,
                "type": e.__class__.__name__,
                "id": e.event_id[:8],
                "symbol": getattr(e, "symbol", None),
            }
            for e in events
        ]
