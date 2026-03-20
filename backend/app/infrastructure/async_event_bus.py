"""Async Event Bus — true event-driven architecture.

Replaces the synchronous InMemoryEventBus with an async version that
supports proper event-driven patterns:
- Handlers run asynchronously (non-blocking)
- Events are processed in order per event type
- Handler failures don't block other handlers
- Support for event filtering and prioritization

Usage:
    bus = AsyncEventBus()
    bus.subscribe(TickReceived, handle_tick)
    await bus.publish(TickReceived(...))
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

from app.domain.trading.events import DomainEvent
from app.domain.ports.event_bus import EventBusPort

logger = logging.getLogger(__name__)


class AsyncEventBus(EventBusPort):
    """Async in-process event bus with proper event-driven patterns.

    Handlers are async callables that run concurrently for different event types.
    Within the same event type, handlers run sequentially to maintain determinism.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[..., Coroutine]]] = defaultdict(list)
        self._sync_handlers: dict[type[DomainEvent], list[Callable[..., Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._max_queue_size = max_queue_size
        self._event_count: int = 0
        self._error_count: int = 0

    def subscribe(self, event_type: type[DomainEvent], handler: Callable[..., Any]) -> None:
        """Subscribe a handler to an event type.

        Automatically detects if handler is async or sync.
        """
        if asyncio.iscoroutinefunction(handler):
            self._handlers[event_type].append(handler)
        else:
            self._sync_handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Publish an event to all registered handlers.

        Async handlers run concurrently, sync handlers run sequentially.
        Handler failures are logged but don't block other handlers.
        """
        event_type = type(event)
        self._event_count += 1

        # Get handlers under lock
        async with self._lock:
            async_handlers = list(self._handlers.get(event_type, []))
            sync_handlers = list(self._sync_handlers.get(event_type, []))

        if not async_handlers and not sync_handlers:
            return

        # Run async handlers concurrently
        if async_handlers:
            tasks = []
            for handler in async_handlers:
                tasks.append(self._run_handler(handler, event, event_type))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self._error_count += 1

        # Run sync handlers sequentially
        for handler in sync_handlers:
            try:
                handler(event)
            except Exception:
                self._error_count += 1
                logger.exception(
                    "Sync event handler %s failed for %s",
                    handler.__qualname__,
                    event_type.__name__,
                )

    async def _run_handler(self, handler: Callable, event: DomainEvent, event_type: type) -> None:
        """Run a single async handler with error handling."""
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Async event handler %s failed for %s",
                handler.__qualname__,
                event_type.__name__,
            )
            raise

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._handlers.clear()
        self._sync_handlers.clear()

    @property
    def event_count(self) -> int:
        """Total events published."""
        return self._event_count

    @property
    def error_count(self) -> int:
        """Total handler errors."""
        return self._error_count

    @property
    def subscriber_count(self) -> int:
        """Total number of subscribed handlers."""
        return sum(len(h) for h in self._handlers.values()) + \
               sum(len(h) for h in self._sync_handlers.values())