"""
Event bus for async event dispatch.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, List, Optional, Set, Type

from brokersv2.core.events import Event

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BackpressureStrategy(Enum):
    """Strategy for handling full queues."""
    DROP_OLDEST = "drop_oldest"
    BLOCK_PRODUCER = "block"
    DROP_NEWEST = "drop_newest"


@dataclass
class Subscription:
    """Event subscription."""
    handler_id: str
    event_type: Type[Event]
    handler: Callable[[Event], Awaitable[None] | None]
    priority: int = 0


class EventBus:
    """
    Async event bus with subscriber isolation.
    
    Features:
    - Subscriber isolation (one slow handler doesn't block others)
    - Dead-letter queue for failed handlers
    - Priority-based dispatch
    - Async and sync handler support
    """
    
    def __init__(
        self,
        max_queue_size: int = 10000,
        strategy: BackpressureStrategy = BackpressureStrategy.DROP_OLDEST,
        max_dlq_size: int = 10000,
    ):
        """
        Initialize event bus with backpressure handling.
        
        Args:
            max_queue_size: Maximum queue size (default: 10,000)
            strategy: Backpressure strategy when queue full
            max_dlq_size: Maximum dead-letter queue size (default: 10,000)
        """
        self._subscriptions: Dict[Type[Event], List[Subscription]] = defaultdict(list)
        self._dlq: List[tuple] = []  # (event, error, subscription)
        self._dlq_max_size = max_dlq_size
        self._running = False
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._dispatcher_task: Optional[asyncio.Task] = None
        self._max_queue_size = max_queue_size
        self._strategy = strategy
        self._dropped_events = 0
        self._queue_lock = asyncio.Lock()  # Protects atomic queue operations
    
    def subscribe(
        self,
        event_type: Type[Event],
        handler: Callable[[Event], Awaitable[None] | None],
        priority: int = 0,
        handler_id: Optional[str] = None,
    ) -> str:
        """
        Subscribe to events of a type.
        
        Returns subscription ID.
        """
        if handler_id is None:
            handler_id = f"{event_type.__name__}_{id(handler)}"
        
        subscription = Subscription(
            handler_id=handler_id,
            event_type=event_type,
            handler=handler,
            priority=priority,
        )
        
        self._subscriptions[event_type].append(subscription)
        # Sort by priority
        self._subscriptions[event_type].sort(key=lambda s: -s.priority)
        
        logger.debug(f"Subscribed {handler_id} to {event_type.__name__}")
        return handler_id
    
    def unsubscribe(self, event_type: Type[Event], handler_id: str) -> bool:
        """Unsubscribe from events."""
        subs = self._subscriptions.get(event_type, [])
        for i, sub in enumerate(subs):
            if sub.handler_id == handler_id:
                subs.pop(i)
                return True
        return False
    
    async def publish(self, event: Event) -> int:
        """
        Publish an event with backpressure handling.
        
        Returns number of handlers called.
        """
        if self._running:
            # Apply backpressure strategy if queue full
            if self._event_queue.full():
                if self._strategy == BackpressureStrategy.DROP_OLDEST:
                    async with self._queue_lock:
                        # Drop oldest event atomically
                        try:
                            self._event_queue.get_nowait()
                            self._dropped_events += 1
                        except asyncio.QueueEmpty:
                            pass
                        self._event_queue.put_nowait(event)
                elif self._strategy == BackpressureStrategy.DROP_NEWEST:
                    # Drop this event
                    self._dropped_events += 1
                    return 0
                elif self._strategy == BackpressureStrategy.BLOCK_PRODUCER:
                    # Block until space available
                    await self._event_queue.put(event)
            else:
                await self._event_queue.put(event)
            return len(self._subscriptions.get(type(event), []))
        else:
            # Direct dispatch if not running
            return await self._dispatch_event(event)
    
    async def _dispatch_event(self, event: Event) -> int:
        """Dispatch event to all subscribers."""
        event_type = type(event)
        subscriptions = self._subscriptions.get(event_type, [])
        
        if not subscriptions:
            return 0
        
        dispatched = 0
        tasks = []
        
        for sub in subscriptions:
            task = asyncio.create_task(self._safe_call_handler(sub, event))
            tasks.append(task)
            dispatched += 1
        
        # Wait for all handlers with timeout
        try:
            await asyncio.wait(tasks, timeout=5.0)
        except Exception as e:
            logger.error(f"Error dispatching event {event_type.__name__}: {e}")
        
        return dispatched
    
    async def _safe_call_handler(self, sub: Subscription, event: Event) -> None:
        """Call handler safely, catching exceptions."""
        try:
            result = sub.handler(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Handler {sub.handler_id} failed for {type(event).__name__}: {e}")
            self._dlq.append((event, e, sub))
            
            # Trim DLQ if it exceeds max size (keep most recent entries)
            if len(self._dlq) > self._dlq_max_size:
                trim_count = len(self._dlq) - self._dlq_max_size
                self._dlq = self._dlq[trim_count:]
                logger.warning(f"DLQ trimmed {trim_count} entries, current size: {len(self._dlq)}")
    
    async def start(self) -> None:
        """Start the event bus dispatcher."""
        self._running = True
        self._dispatcher_task = asyncio.create_task(self._dispatcher_loop())
    
    async def stop(self) -> None:
        """Stop the event bus."""
        self._running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
    
    async def _dispatcher_loop(self) -> None:
        """Main dispatcher loop."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                await self._dispatch_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Dispatcher error: {e}")
    
    def get_dlq_size(self) -> int:
        """Get dead-letter queue size."""
        return len(self._dlq)
    
    def get_dlq(self) -> List[tuple]:
        """Get dead-letter queue contents."""
        return self._dlq.copy()
    
    def clear_dlq(self) -> None:
        """Clear dead-letter queue."""
        self._dlq.clear()
    
    @property
    def queue_depth(self) -> int:
        """Get current queue depth."""
        return self._event_queue.qsize()
    
    @property
    def queue_depths(self) -> Dict[str, int]:
        """Get queue depth metrics."""
        return {
            "event_queue": self._event_queue.qsize(),
            "dlq_size": len(self._dlq),
            "max_size": self._max_queue_size,
            "dropped_events": self._dropped_events,
        }
    
    @property
    def is_queue_full(self) -> bool:
        """Check if event queue is full."""
        return self._event_queue.full()