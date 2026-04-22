"""Resilient handler wrapper — error isolation for event handlers.

Wraps any IEventHandler with a try/except that:
1. Logs the error with full context
2. Does NOT re-raise (one handler failure shouldn't break others)
3. Optionally publishes a HandlerErrorEvent for observability
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.trading.events import DomainEvent

if TYPE_CHECKING:
    from app.application.events.handler import IEventHandler
    from app.domain.trading.event_store import EventBus

logger = logging.getLogger(__name__)


class ResilientHandlerWrapper:
    """Wraps an IEventHandler with error isolation.

    Usage:
        handler = TickReceivedHandler(...)
        wrapped = ResilientHandlerWrapper(handler, event_bus)
        event_bus.subscribe("TickReceived", wrapped)
    """

    def __init__(self, handler: "IEventHandler", event_bus: "EventBus | None" = None):
        self._handler = handler
        self._event_bus = event_bus

    def __call__(self, event: DomainEvent) -> None:
        try:
            self._handler.handle(event)
        except Exception:
            logger.exception(
                "Handler %s failed for event %s: %s",
                type(self._handler).__name__,
                type(event).__name__,
                event,
            )

    @property
    def handler(self) -> "IEventHandler":
        """Access the wrapped handler (for testing)."""
        return self._handler
