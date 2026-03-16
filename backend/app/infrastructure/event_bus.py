"""In-memory event bus — synchronous publish/subscribe implementation.

Implements the EventBusPort contract. Handlers are invoked synchronously
in registration order, keeping the system deterministic and easy to test.

Thread safety: A lock protects the _handlers dict. publish() copies the
handler list under the lock, then iterates outside it so that handler
execution does not block subscribe/clear operations.
"""

from __future__ import annotations

import logging
import threading
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
        self._lock = threading.Lock()

    def subscribe(self, event_type: type[DomainEvent], handler: Callable[..., Any]) -> None:
        with self._lock:
            self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        event_type = type(event)
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        for handler in handlers:
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
        with self._lock:
            self._handlers.clear()
