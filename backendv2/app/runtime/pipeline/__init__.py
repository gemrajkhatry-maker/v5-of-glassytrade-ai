"""Pipeline core — PipelineStage trait, SPSC queue, event types."""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Generic, Optional, Protocol, TypeVar, runtime_checkable
from app.runtime.pipeline.events import PipelineEvent
from app.runtime.pipeline.base import PipelineStageBase

T = TypeVar("T")


@runtime_checkable
class PipelineStage(Protocol):
    """A single stage in the deterministic tick processing pipeline.

    Each stage:
    - Owns its input queue
    - Owns its mutable state
    - Produces output events consumed by the next stage
    - Runs synchronously in the hot path
    - Has no knowledge of other stages
    """

    def name(self) -> str:
        """Human-readable stage name for telemetry."""
        ...

    def process(self, event: PipelineEvent | object) -> list[PipelineEvent | object]:
        """Process one input event, return zero or more output events.

        Must be:
        - Deterministic: same input → same output
        - Allocation-free in hot path
        - Exception-safe: catch and log, return empty list on failure
        """
        ...

    def warmup(self) -> None:
        """Pre-allocate state, load metadata. Called once at startup."""
        ...

    def teardown(self) -> None:
        """Flush state, persist if needed. Called once at shutdown."""
        ...

    def reset(self) -> None:
        """Reset to initial state. Called before restarting deterministic processing."""
        ...


class SPSCQueue(Generic[T]):
    """Single-producer single-consumer lock-free queue.

    Fixed capacity ring buffer. No allocations after init.
    Used between pipeline stages for zero-copy event passing.
    """

    def __init__(self, capacity: int = 1024):
        self._capacity = capacity
        self._buffer: list[Optional[T]] = [None] * capacity
        self._head = 0  # producer index
        self._tail = 0  # consumer index
        self._size = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return self._size

    @property
    def empty(self) -> bool:
        return self._size == 0

    @property
    def full(self) -> bool:
        return self._size >= self._capacity

    def push(self, item: T) -> bool:
        """Push one item. Returns False if queue is full."""
        if self.full:
            return False
        self._buffer[self._head] = item
        self._head = (self._head + 1) % self._capacity
        self._size += 1
        return True

    def pop(self) -> Optional[T]:
        """Pop one item. Returns None if queue is empty."""
        if self.empty:
            return None
        item = self._buffer[self._tail]
        self._buffer[self._tail] = None
        self._tail = (self._tail + 1) % self._capacity
        self._size -= 1
        return item

    def drain(self) -> list[T]:
        """Drain all items. Used at shutdown or to reset for reprocessing."""
        items: list[T] = []
        while not self.empty:
            item = self.pop()
            if item is not None:
                items.append(item)
        return items

    def clear(self) -> None:
        """Clear all items without processing."""
        self._buffer = [None] * self._capacity
        self._head = 0
        self._tail = 0
        self._size = 0


@dataclass
class StageMetrics:
    """Latency and throughput metrics for one pipeline stage."""
    stage_name: str = ""
    processed_count: int = 0
    error_count: int = 0
    total_latency_ns: int = 0
    max_latency_ns: int = 0
    min_latency_ns: int = 0

    @property
    def avg_latency_ns(self) -> float:
        if self.processed_count == 0:
            return 0.0
        return self.total_latency_ns / self.processed_count

    def record(self, latency_ns: int) -> None:
        self.processed_count += 1
        self.total_latency_ns += latency_ns
        if latency_ns > self.max_latency_ns:
            self.max_latency_ns = latency_ns
        if self.min_latency_ns == 0 or latency_ns < self.min_latency_ns:
            self.min_latency_ns = latency_ns

    def record_error(self) -> None:
        self.error_count += 1

    def reset(self) -> None:
        self.processed_count = 0
        self.error_count = 0
        self.total_latency_ns = 0
        self.max_latency_ns = 0
        self.min_latency_ns = 0