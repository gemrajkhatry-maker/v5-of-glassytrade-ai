"""Channel — typed bounded async queue connecting processors.

Backpressure: send() blocks when channel is full. This surfaces throughput
bottlenecks at development time, not in production.
"""
from __future__ import annotations
import asyncio
import logging
from typing import TypeVar, Generic, AsyncIterator

T = TypeVar("T")
logger = logging.getLogger(__name__)

class Channel(Generic[T]):
    """Bounded async queue between two processors.

    Usage:
        ch = Channel[RawTickMessage]("raw_ticks", capacity=1000)
        await ch.send(msg)        # blocks if full (backpressure)
        async for msg in ch:      # yields messages forever
            ...
    """

    def __init__(self, name: str, capacity: int = 1000) -> None:
        self.name = name
        self.capacity = capacity
        self._queue: asyncio.Queue[T | None] = asyncio.Queue(maxsize=capacity)
        self._sent = 0
        self._received = 0

    async def send(self, msg: T) -> None:
        """Send a message. Blocks if channel is at capacity (backpressure)."""
        await self._queue.put(msg)
        self._sent += 1

    async def send_nowait(self, msg: T) -> bool:
        """Non-blocking send. Returns False if channel is full."""
        try:
            self._queue.put_nowait(msg)
            self._sent += 1
            return True
        except asyncio.QueueFull:
            logger.warning("Channel '%s' full (capacity=%d), dropping message", self.name, self.capacity)
            return False

    async def receive(self) -> T:
        """Receive a message. Blocks if empty."""
        msg = await self._queue.get()
        self._received += 1
        return msg  # type: ignore[return-value]

    def __aiter__(self) -> AsyncIterator[T]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[T]:
        """Yields messages forever until None sentinel is received."""
        while True:
            msg = await self._queue.get()
            self._received += 1
            if msg is None:
                break
            yield msg

    async def close(self) -> None:
        """Signal consumers to stop by sending None sentinel."""
        await self._queue.put(None)  # type: ignore[arg-type]

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def stats(self) -> dict:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "qsize": self.qsize,
            "sent": self._sent,
            "received": self._received,
        }
