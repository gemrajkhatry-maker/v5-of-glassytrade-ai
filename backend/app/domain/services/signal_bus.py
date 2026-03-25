"""Signal Bus — asyncio.Queue-based signal routing.

All sessions produce Signal objects onto the bus. The PortfolioCoordinator
consumes from the bus and makes portfolio-level decisions.

Thread-safe by design (asyncio.Queue). No locks needed.
Max queue size: 50 (backpressure — if queue fills, sessions block).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import time

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BusSignal:
    """Wrapper for signal on the bus with metadata."""

    signal: Signal
    symbol: str
    source: str = "amt"  # "amt" | "agent" | "rl"
    priority: int = 0  # higher = more important
    timestamp: float = field(default_factory=time.time)

    def __lt__(self, other: BusSignal) -> bool:
        return self.priority < other.priority


class SignalBus:
    """Asyncio Queue-based signal bus for multi-symbol signal routing.

    Sessions put signals onto the bus. PortfolioCoordinator consumes from it.
    """

    def __init__(self, maxsize: int = 50) -> None:
        self._queue: asyncio.Queue[BusSignal] = asyncio.Queue(maxsize=maxsize)
        self._produced: int = 0
        self._consumed: int = 0
        self._rejected: int = 0

    async def put(self, bus_signal: BusSignal) -> bool:
        """Put a signal on the bus. Returns False if queue is full (backpressure)."""
        try:
            self._queue.put_nowait(bus_signal)
            self._produced += 1
            return True
        except asyncio.QueueFull:
            logger.warning(
                "Signal bus full — dropping signal for %s (source=%s)",
                bus_signal.symbol,
                bus_signal.source,
            )
            return False

    async def get(self) -> BusSignal:
        """Get the next signal from the bus (blocks until available)."""
        return await self._queue.get()

    def get_nowait(self) -> BusSignal | None:
        """Non-blocking get. Returns None if queue is empty."""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        return self._queue.empty()

    def record_rejection(self) -> None:
        """Record a signal rejection by PortfolioCoordinator."""
        self._rejected += 1

    def get_stats(self) -> dict:
        """Get bus statistics."""
        return {
            "queue_size": self.size,
            "produced": self._produced,
            "consumed": self._consumed,
            "rejected": self._rejected,
        }
