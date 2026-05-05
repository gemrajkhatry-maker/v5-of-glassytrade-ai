"""Application event bus — the central nervous system of the trading backend.

All state mutations flow through this bus. Services subscribe to event types
and react. The bus ensures:
- Idempotency (duplicate event prevention)
- Error isolation (handler failures don't crash the bus)
- Event history (for replay and debugging)
- Per-symbol isolation (symbol-scoped handlers)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Callable, Type

from app.domain.shared.event.base import DomainEvent

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """
    In-memory event bus with idempotency, error isolation, and replay.

    This is the application-level event bus. It is the single integration
    mechanism between services. No service directly mutates another service's
    state — they communicate exclusively via events.

    Usage:
        bus = EventBus()

        # Subscribe
        bus.subscribe(TickReceived, my_handler)

        # Publish
        bus.publish(TickReceived(symbol="BTCUSDT", price=50000.0, ...))
    """

    def __init__(self, max_history: int = 10000):
        self._handlers: dict[Type[DomainEvent], list[EventHandler]] = defaultdict(list)
        self._seen_event_ids: set[str] = set()
        self._event_history: list[DomainEvent] = []
        self._max_history = max_history
        self._error_counts: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, event_type: Type[DomainEvent], handler: EventHandler) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: The event class to subscribe to
            handler: Callable that receives the event
        """
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug(
                "Subscribed %s to %s",
                handler.__name__,
                event_type.__name__,
            )

    def unsubscribe(self, event_type: Type[DomainEvent], handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    def get_subscribers(self, event_type: Type[DomainEvent]) -> list[EventHandler]:
        """Get all handlers subscribed to an event type."""
        return list(self._handlers.get(event_type, []))

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event: DomainEvent) -> int:
        """Publish an event to all subscribers.

        Idempotent: duplicate event_ids are silently dropped.
        Error-isolated: handler failures are caught and logged, never propagated.

        Args:
            event: The domain event to publish

        Returns:
            Number of handlers that processed the event
        """
        # Idempotency check
        if event.event_id in self._seen_event_ids:
            logger.debug("Duplicate event dropped: %s", event)
            return 0

        self._seen_event_ids.add(event.event_id)

        # Record in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history // 2:]

        # Dispatch to handlers
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        handled_count = 0

        for handler in handlers:
            try:
                handler(event)
                handled_count += 1
            except Exception as e:
                self._error_counts[handler.__name__] += 1
                logger.error(
                    "Handler %s failed for %s: %s (total errors: %d)",
                    handler.__name__,
                    event_type.__name__,
                    e,
                    self._error_counts[handler.__name__],
                    exc_info=True,
                )
                # Error isolation: continue to next handler

        return handled_count

    # ------------------------------------------------------------------
    # History & Replay
    # ------------------------------------------------------------------

    def get_history(
        self,
        event_type: Type[DomainEvent] | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
        """Get event history, optionally filtered."""
        events = self._event_history

        if event_type:
            events = [e for e in events if isinstance(e, event_type)]

        if symbol:
            events = [
                e for e in events
                if hasattr(e, "symbol") and e.symbol == symbol
            ]

        return events[-limit:]

    def replay(
        self,
        event_type: Type[DomainEvent] | None = None,
        symbol: str | None = None,
    ) -> int:
        """Replay matching events to current subscribers.

        Returns the number of events replayed.
        """
        events = self.get_history(event_type=event_type, symbol=symbol, limit=self._max_history)
        count = 0
        for event in events:
            handlers = self._handlers.get(type(event), [])
            for handler in handlers:
                try:
                    handler(event)
                    count += 1
                except Exception as e:
                    logger.error("Replay handler %s failed: %s", handler.__name__, e)
        return count

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get bus statistics."""
        return {
            "total_event_types": len(self._handlers),
            "total_handlers": sum(len(h) for h in self._handlers.values()),
            "seen_events": len(self._seen_event_ids),
            "history_size": len(self._event_history),
            "error_counts": dict(self._error_counts),
        }

    def clear_seen_ids(self) -> None:
        """Clear the seen event IDs cache (for testing)."""
        self._seen_event_ids.clear()

    def clear_history(self) -> None:
        """Clear event history (for testing)."""
        self._event_history.clear()

    def reset(self) -> None:
        """Reset the bus completely (for testing)."""
        self._handlers.clear()
        self._seen_event_ids.clear()
        self._event_history.clear()
        self._error_counts.clear()
