"""In-memory event bus — synchronous publish/subscribe implementation.

Implements the EventBusPort contract. Handlers are invoked synchronously
in registration order, keeping the system deterministic and easy to test.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

from app.domain.trading.events import DomainEvent
from app.domain.ports.event_bus import EventBusPort

logger = logging.getLogger(__name__)


class InMemoryEventBus(EventBusPort):
    """Synchronous in-process event bus.

    Handlers are plain callables. They receive the event as the sole argument.
    If a handler raises, others are still called and the exception is logged.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[..., Any]]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Callable[..., Any]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        event_type = type(event)
        for handler in self._handlers.get(event_type, []):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "Event handler %s failed for %s",
                    handler.__qualname__,
                    event_type.__name__,
                )

    def clear(self) -> None:
        """Remove all subscriptions (useful in tests)."""
        self._handlers.clear()
