"""In-process event bus with deterministic dispatch semantics.

The bus owns no runtime control logic. It only routes immutable events between
subscribed handlers and preserves diagnostics as an immutable audit trail.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any, DefaultDict, Dict, List, Type
import logging

from app.domain.shared.event.base import DomainEvent

logger = logging.getLogger(__name__)


EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """Simple event bus with idempotency and read-only history.

    The bus intentionally has no historic reconstruction execution path. It stores events only for
    audit readout and deterministic debugging.
    """

    def __init__(self, max_history: int = 10_000):
        self._handlers: DefaultDict[Type[DomainEvent], list[EventHandler]] = defaultdict(list)
        self._seen_event_ids: set[str] = set()
        self._event_history: list[DomainEvent] = []
        self._max_history = max_history
        self._error_counts: dict[str, int] = defaultdict(int)

    def subscribe(self, event_type: Type[DomainEvent], handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: Type[DomainEvent], handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    def get_subscribers(self, event_type: Type[DomainEvent]) -> list[EventHandler]:
        """Return all handlers for an event type."""
        return list(self._handlers.get(event_type, []))

    def publish(self, event: DomainEvent) -> int:
        """Publish an event and return the number of handlers that succeeded."""
        if event.event_id in self._seen_event_ids:
            return 0

        self._seen_event_ids.add(event.event_id)

        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-(self._max_history // 2):]

        handled_count = 0
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            try:
                handler(event)
                handled_count += 1
            except Exception as exc:
                self._error_counts[handler.__name__] += 1
                logger.error(
                    "EventBus handler %s failed for %s: %s",
                    handler.__name__,
                    type(event).__name__,
                    exc,
                    exc_info=True,
                )

        return handled_count

    def get_history(
        self,
        event_type: Type[DomainEvent] | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
        """Read-only event history, optionally filtered."""
        events = self._event_history

        if event_type is not None:
            events = [e for e in events if isinstance(e, event_type)]

        if symbol is not None:
            events = [e for e in events if getattr(e, "symbol", None) == symbol]

        return events[-limit:]

    def get_timeline(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Read-only timeline for audit and parity checks."""
        return [
            {
                "event_type": type(e).__name__,
                "event_id": e.event_id,
                "timestamp": getattr(e, "timestamp", None),
                "symbol": getattr(e, "symbol", None),
            }
            for e in self.get_history(symbol=symbol, limit=limit)
        ]

    def get_stats(self) -> dict[str, Any]:
        """Diagnostic counters."""
        return {
            "total_event_types": len(self._handlers),
            "total_handlers": sum(len(handlers) for handlers in self._handlers.values()),
            "seen_events": len(self._seen_event_ids),
            "history_size": len(self._event_history),
            "error_counts": dict(self._error_counts),
        }

    def clear_seen_ids(self) -> None:
        """Clear seen event IDs (test helper)."""
        self._seen_event_ids.clear()

    def clear_history(self) -> None:
        """Clear in-memory event history (test helper)."""
        self._event_history.clear()

    def reset(self) -> None:
        """Reset handlers and diagnostics."""
        self._handlers.clear()
        self._seen_event_ids.clear()
        self._event_history.clear()
        self._error_counts.clear()
    
    def clear_seen_ids(self) -> None:
        """Clear the seen event IDs cache (for testing)."""
        self._seen_event_ids.clear()