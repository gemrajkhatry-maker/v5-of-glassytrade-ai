"""History seed scheduler with rate-limit handling (Phase 0.5).

The previous AMT seed logic had retry handling but no global scheduler —
every engine independently hit Dhan during startup, causing DH-3001 rate
limits. Seed status was also not exposed for readiness/telemetry.

This module provides:
- SeedStatus enum: NOT_STARTED, SEEDING, READY, DEGRADED_RATE_LIMIT,
  DEGRADED_EMPTY, FAILED
- HistorySeedScheduler: one shared request scheduler across all engines
  that enforces minimum delay between requests, caches successful fetches,
  deduplicates concurrent requests, and retries on transient failures.
- seed_status(): convenience function to read status from an engine.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SeedStatus(str, Enum):
    """Per-engine history seed state."""
    NOT_STARTED = "NOT_STARTED"
    SEEDING = "SEEDING"
    READY = "READY"
    DEGRADED_RATE_LIMIT = "DEGRADED_RATE_LIMIT"
    DEGRADED_EMPTY = "DEGRADED_EMPTY"
    FAILED = "FAILED"


def seed_status(engine: Any) -> SeedStatus:
    """Read the seed status from an engine.

    Returns SeedStatus.NOT_STARTED if the engine has no _seed_status attribute.
    """
    return getattr(engine, "_seed_status", SeedStatus.NOT_STARTED)


class HistorySeedScheduler:
    """Shared history-fetch scheduler across all engines.

    Prevents every engine from independently hitting Dhan during startup
    by serializing requests through one scheduler with a minimum interval
    between fetches. Also caches successful fetches and deduplicates
    concurrent requests for the same symbol.
    """

    def __init__(
        self,
        history_source: Any,
        *,
        min_interval_sec: float = 0.5,
        max_retries: int = 3,
        base_delay_sec: float = 1.0,
        cache_ttl_sec: float = 300.0,
    ) -> None:
        self._history_source = history_source
        self._min_interval = min_interval_sec
        self._max_retries = max_retries
        self._base_delay = base_delay_sec
        self._cache_ttl = cache_ttl_sec
        self._lock = threading.Lock()
        self._last_fetch_time: float = 0.0
        self._cache: dict[str, tuple[float, list]] = {}
        self._in_flight: dict[str, threading.Event] = {}
        self._in_flight_count: int = 0

    @property
    def in_flight(self) -> int:
        """Number of currently in-flight fetch operations."""
        with self._lock:
            return self._in_flight_count

    def fetch(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list | None:
        """Fetch history for a symbol, with caching, dedup, and retries.

        Returns the candle list on success, None on failure (degraded).
        """
        cache_key = f"{symbol}:{interval}"
        # Check cache first
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (time.monotonic() - cached[0]) < self._cache_ttl:
                logger.info("seed scheduler: cache hit for %s", symbol)
                return list(cached[1])
            # Check for in-flight request
            if cache_key in self._in_flight:
                event = self._in_flight[cache_key]
                self._lock.release()
                try:
                    event.wait(timeout=30.0)
                finally:
                    self._lock.acquire()
                # After waiting, check cache again
                cached = self._cache.get(cache_key)
                if cached:
                    return list(cached[1])
                return None

        # Mark in-flight
        event = threading.Event()
        with self._lock:
            self._in_flight[cache_key] = event
            self._in_flight_count += 1

        try:
            result = self._fetch_with_retry(symbol, interval, limit)
            if result is not None:
                with self._lock:
                    self._cache[cache_key] = (time.monotonic(), list(result))
            return result
        finally:
            with self._lock:
                self._in_flight_count -= 1
                self._in_flight.pop(cache_key, None)
            event.set()

    def _fetch_with_retry(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list | None:
        """Fetch with rate-limit spacing and exponential backoff retries."""
        for attempt in range(1, self._max_retries + 1):
            # Enforce minimum interval between requests
            with self._lock:
                elapsed = time.monotonic() - self._last_fetch_time
                if elapsed < self._min_interval:
                    sleep_time = self._min_interval - elapsed
                    logger.info("seed scheduler: rate-limit sleep %.2fs", sleep_time)
                    time.sleep(sleep_time)
                self._last_fetch_time = time.monotonic()

            try:
                result = self._history_source.fetch_history(symbol, interval, limit)
                if result is not None and len(result) > 0:
                    return list(result)
                if result is not None:
                    # Empty result — no history available
                    return []
            except Exception as exc:
                is_transient = isinstance(exc, (TimeoutError, ConnectionError, OSError))
                if not is_transient:
                    logger.error("seed scheduler: unexpected error for %s", symbol, exc_info=True)
                logger.warning(
                    "seed scheduler: fetch failed for %s (attempt %d/%d): %s",
                    symbol, attempt, self._max_retries, exc,
                )
                if attempt < self._max_retries and is_transient:
                    delay = self._base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
                    logger.info("seed scheduler: retry %d/%d in %.1fs", attempt + 1, self._max_retries, delay)
                    time.sleep(delay)
        return None
