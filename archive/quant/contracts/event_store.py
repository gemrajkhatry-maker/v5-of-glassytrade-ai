"""Event Store - Append-Only Store for Domain Events.

The Event Store is the source of truth for all domain events.
It provides:
1. Append-only storage (no updates or deletes)
2. Idempotency detection (prevent duplicate events)
3. Event ordering (timestamp-based)
4. Query capabilities (get events for a specific trade/entity)
5. Deterministic verification (reconstruct state from events)

DESIGN PRINCIPLES:
- Events are immutable (frozen=True)
- Idempotency key prevents duplicate processing
- Events are never modified or deleted
- Query by aggregate_id for trade-specific verification
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from quant.contracts.events import DomainEvent

logger = logging.getLogger(__name__)


T = TypeVar("T", bound=DomainEvent)


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

    Implementations can use:
    - InMemoryEventStore (for testing/development)
    - SQLiteEventStore (for production)
    - KafkaEventStore (for distributed systems)
    """

    @abstractmethod
    def append(self, event: DomainEvent) -> None:
        """Append an event to the store.

        Raises DuplicateEventError if idempotency_key already exists.
        """
        pass

    @abstractmethod
    def get_events(
        self,
        aggregate_id: str | None = None,
        event_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[DomainEvent]:
        """Query events by criteria.

        Args:
            aggregate_id: Filter by trade_id or symbol
            event_type: Filter by event class name
            start_time: ISO timestamp string
            end_time: ISO timestamp string

        Returns:
            List of events matching criteria, ordered by timestamp
        """
        pass

    @abstractmethod
    def get_event_count(self, aggregate_id: str | None = None) -> int:
        """Get total event count, optionally filtered by aggregate_id."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all events (for testing)."""
        pass


class InMemoryEventStore(EventStore):
    """In-memory event store implementation.

    Thread-safe using a reentrant lock.
    Suitable for development and testing.
    """

    def __init__(self):
        self._events: list[DomainEvent] = []
        self._idempotency_keys: set[str] = set()
        self._lock = threading.RLock()
        self._aggregate_index: dict[
            str, list[int]
        ] = {}  # aggregate_id -> event indices

    def append(self, event: DomainEvent) -> None:
        with self._lock:
            # Check idempotency
            if event.idempotency_key in self._idempotency_keys:
                logger.warning(f"Duplicate event detected: {event.idempotency_key}")
                raise DuplicateEventError(event.idempotency_key)

            # Store event
            self._events.append(event)
            self._idempotency_keys.add(event.idempotency_key)

            # Index by aggregate (trade_id if available)
            if hasattr(event, "trade_id") and event.trade_id:
                trade_id = event.trade_id
                if trade_id not in self._aggregate_index:
                    self._aggregate_index[trade_id] = []
                self._aggregate_index[trade_id].append(len(self._events) - 1)

            if hasattr(event, "symbol") and event.symbol:
                symbol = event.symbol
                if symbol not in self._aggregate_index:
                    self._aggregate_index[symbol] = []
                self._aggregate_index[symbol].append(len(self._events) - 1)

            logger.debug(f"Event appended: {event}")

    def get_events(
        self,
        aggregate_id: str | None = None,
        event_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[DomainEvent]:
        with self._lock:
            results = list(self._events)

            # Filter by aggregate
            if aggregate_id:
                if aggregate_id in self._aggregate_index:
                    indices = self._aggregate_index[aggregate_id]
                    results = [self._events[i] for i in indices]
                else:
                    return []

            # Filter by event type
            if event_type:
                results = [e for e in results if e.__class__.__name__ == event_type]

            # Filter by time range
            if start_time:
                results = [e for e in results if e.timestamp >= start_time]
            if end_time:
                results = [e for e in results if e.timestamp <= end_time]

            # Legacy events have no stream cursor. Keep them timestamp ordered;
            # only use explicit sequence ordering when every event in the result
            # belongs to the sequenced stream. This avoids placing all legacy
            # events before newer sequenced events during migration.
            if results and all(event.ordering_sequence > 0 for event in results):
                return sorted(
                    results,
                    key=lambda event: (
                        event.session_id,
                        event.ordering_sequence,
                        event.timestamp,
                        event.event_id,
                    ),
                )
            return sorted(
                results,
                key=lambda event: (event.timestamp, event.event_id),
            )

    def get_event_count(self, aggregate_id: str | None = None) -> int:
        with self._lock:
            if aggregate_id:
                return len(self._aggregate_index.get(aggregate_id, []))
            return len(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._idempotency_keys.clear()
            self._aggregate_index.clear()


# ---------------------------------------------------------------------------
# Event Bus - In-Memory Pub/Sub
# ---------------------------------------------------------------------------


class EventBus:
    """In-memory event bus for pub/sub pattern.

    Handlers subscribe to specific event types and are notified
    when those events are published.
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable[[DomainEvent], None]]] = {}
        self._lock = threading.RLock()
        self._event_store: EventStore | None = None

    def set_event_store(self, store: EventStore) -> None:
        """Set the event store for persistence."""
        self._event_store = store

    def subscribe(
        self, event_type: str, handler: Callable[[DomainEvent], None]
    ) -> None:
        """Subscribe to events of a specific type."""
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
            logger.debug(f"Handler subscribed to {event_type}")

    def unsubscribe(
        self, event_type: str, handler: Callable[[DomainEvent], None]
    ) -> None:
        """Unsubscribe a handler."""
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type].remove(handler)

    def publish(self, event: DomainEvent) -> None:
        """Publish an event to all subscribers.

        Also persists the event to the event store if configured.

        Idempotency: If event is a duplicate (same idempotency_key),
        handlers are NOT notified - prevents double execution.
        """
        event_type = event.__class__.__name__

        # Persist to event store - this checks idempotency
        is_duplicate = False
        if self._event_store:
            try:
                self._event_store.append(event)
            except DuplicateEventError:
                is_duplicate = True
                logger.debug(f"Duplicate event skipped: {event.idempotency_key}")
            except Exception as e:
                logger.error(f"Failed to persist event: {e}")

        # Only notify handlers for NEW events (not duplicates)
        # This ensures true idempotency - same event won't be processed twice
        if is_duplicate:
            return

        # Notify handlers for new events
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
            global_handlers = list(self._handlers.get("*", []))

        for handler in handlers + global_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Handler error for {event_type}: {e}")

    def get_handlers(self, event_type: str) -> list[Callable[[DomainEvent], None]]:
        """Get all handlers for an event type."""
        with self._lock:
            return list(self._handlers.get(event_type, []))


# ---------------------------------------------------------------------------
# Session Context (Dependency Injection)
# ---------------------------------------------------------------------------

from contextvars import ContextVar
from typing import Optional
import threading

# Context variables for session-scoped event system
# These allow multiple trading sessions in the same process
_event_bus_context: ContextVar[Optional[EventBus]] = ContextVar(
    "event_bus", default=None
)
_event_store_context: ContextVar[Optional[EventStore]] = ContextVar(
    "event_store", default=None
)


class EventSystem:
    """Session-scoped event system with dependency injection.

    This class provides proper isolation for multiple trading sessions
    running in the same process.

    Usage:
        # Per-session (recommended)
        system = EventSystem()
        bus = system.event_bus
        store = system.event_store

        # Or use context manager
        with EventSystem() as system:
            bus = system.event_bus
    """

    def __init__(self, store_type: str = "memory"):
        self._store_type = store_type
        self._event_bus: Optional[EventBus] = None
        self._event_store: Optional[EventStore] = None

    @property
    def event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = EventBus()
            if self._event_store:
                self._event_bus.set_event_store(self._event_store)
        return self._event_bus

    @property
    def event_store(self) -> EventStore:
        if self._event_store is None:
            if self._store_type == "memory":
                self._event_store = InMemoryEventStore()
            else:
                raise ValueError(f"Unknown store type: {self._store_type}")
        return self._event_store

    def __enter__(self) -> "EventSystem":
        """Set this system as the current context."""
        _event_bus_context.set(self._event_bus)
        _event_store_context.set(self._event_store)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Clear this system from the context."""
        _event_bus_context.set(None)
        _event_store_context.set(None)


# ---------------------------------------------------------------------------
# Audit Trail Verifier
# ---------------------------------------------------------------------------


class AuditTrailVerifier:
    """Audit trail verifier for deterministic State reconstruction.

    Given a list of events, verifies that applying them produces consistent
    state. This is for audit trail verification, not for simulation execution.
    """

    def __init__(self, event_store: EventStore):
        self._event_store = event_store
        self._state_handlers: dict[str, Callable[[DomainEvent], Any]] = {}

    def register_handler(
        self, event_type: str, handler: Callable[[DomainEvent], Any]
    ) -> None:
        """Register a handler for event verification."""
        self._state_handlers[event_type] = handler

    def verify_to(
        self, timestamp: str | None = None, aggregate_id: str | None = None
    ) -> dict[str, Any]:
        """Verify events up to timestamp/aggregate and return reconstructed state.

        For audit trail verification, not for simulation execution.

        Returns a dict with:
        - trades: dict of trade_id -> trade state
        - positions: dict of trade_id -> position state
        - events: list of all events
        """
        events = self._event_store.get_events(
            aggregate_id=aggregate_id,
            end_time=timestamp,
        )

        # Initialize state
        state = {
            "trades": {},
            "positions": {},
            "events": events,
        }

        # Apply each event to reconstruct state
        for event in events:
            event_type = event.__class__.__name__
            if event_type in self._state_handlers:
                self._state_handlers[event_type](event, state)

        return state

    def verify_determinism(self, events: list[DomainEvent]) -> bool:
        """Verify that event verification produces consistent results.

        Runs verification twice and compares outputs to ensure
        deterministic behavior of state reconstruction.
        """
        state1 = self._verify_events(events)
        state2 = self._verify_events(events)
        return state1 == state2

    def _verify_events(self, events: list[DomainEvent]) -> dict[str, Any]:
        """Internal verification implementation."""
        state = {}
        for event in events:
            event_type = event.__class__.__name__
            if event_type in self._state_handlers:
                state = self._state_handlers[event_type](event, state)
        return state
