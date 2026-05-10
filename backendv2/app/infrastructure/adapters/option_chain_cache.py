"""Option chain cache with TTL eviction.

Extracted from DhanAdapter to separate the caching concern from the
broker adapter.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class _TimedCache(Generic[T]):
    """Thread-safe cache with TTL eviction."""

    def __init__(self, ttl_sec: float) -> None:
        self._ttl_sec = ttl_sec
        self._data: dict[tuple, tuple[T, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple) -> T | None:
        """Return cached value if not expired, else None."""
        if self._ttl_sec <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            value, ts = hit
            if now - ts > self._ttl_sec:
                # expired — remove
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: tuple, value: T) -> None:
        """Store value with current timestamp."""
        if self._ttl_sec <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._data[key] = (value, now)
            # Evict expired entries
            self._data = {
                k: v
                for k, v in self._data.items()
                if now - v[1] <= self._ttl_sec + 1
            }

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._data.clear()

    @property
    def ttl_sec(self) -> float:
        return self._ttl_sec


class OptionChainCache:
    """Cache for option chain API responses.

    Keyed by (underlying, exchange, expiry_index) with configurable TTL.
    """

    def __init__(self, ttl_sec: float = 30.0) -> None:
        self._cache = _TimedCache[object](ttl_sec)

    def get(self, underlying: str, exchange: str, expiry_index: int) -> object | None:
        """Return cached option chain or None if miss/expired."""
        key = (underlying.upper(), exchange.upper(), int(expiry_index))
        return self._cache.get(key)

    def set(self, underlying: str, exchange: str, expiry_index: int, chain: object) -> None:
        """Cache an option chain."""
        key = (underlying.upper(), exchange.upper(), int(expiry_index))
        self._cache.set(key, chain)

    def clear(self) -> None:
        """Clear all cached chains."""
        self._cache.clear()

    @property
    def ttl_sec(self) -> float:
        return self._cache.ttl_sec
