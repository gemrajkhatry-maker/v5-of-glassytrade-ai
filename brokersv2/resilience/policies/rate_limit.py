"""
Canonical rate limiting — single source of truth.

Two distinct limiters are provided because they serve different purposes:

ProviderRateLimiter  (formerly TokenBucketRateLimiter in providers/rate_limiter.py)
    Async, single-user, designed for unofficial / unofficial-rate-limited
    external providers such as OpenChart.  Features: jitter, cooldown after
    consecutive failures, record_success/record_failure feedback.

BrokerRateLimiter  (formerly RateLimiter in infrastructure/rate_limiter/token_bucket.py)
    Sync, multi-bucket, hard-coded to DhanHQ v2 API limits
    (orders/quotes/historical/option-chain/non-trading buckets).
    Used by DhanHttpClient and DhanBrokerAdapter.

Backward-compat aliases are provided so that existing importers do not need
to change:
    providers/rate_limiter.py          → re-exports ProviderRateLimiter as TokenBucketRateLimiter
    infrastructure/rate_limiter/token_bucket.py → re-exports BrokerRateLimiter as RateLimiter
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import random
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ProviderRateLimiter — async, single-user, with jitter and cooldown
# =============================================================================

class ProviderRateLimiter:
    """
    Async token-bucket limiter for single-user external provider calls.

    Designed for providers that have no guaranteed rate-limit contract
    (e.g., OpenChart).  Adds randomised jitter to prevent request clustering
    and enters a cooldown period after repeated failures.

    Usage:
        limiter = ProviderRateLimiter(rate=2.0, burst=5)
        await limiter.acquire()
        try:
            result = await fetch()
            limiter.record_success()
        except Exception:
            limiter.record_failure()
    """

    def __init__(
        self,
        rate: float = 2.0,
        burst: int = 5,
        cooldown_after: int = 3,
        cooldown_duration: float = 5.0,
        jitter_min: float = 0.05,
        jitter_max: float = 0.15,
    ):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")
        if cooldown_after <= 0:
            raise ValueError("cooldown_after must be positive")

        self._rate = rate
        self._burst = burst
        self._cooldown_after = cooldown_after
        self._cooldown_duration = cooldown_duration
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max

        self._tokens: float = float(burst)
        self._last_refill: float = time.time()
        self._failure_count: int = 0
        self._cooldown_until: float = 0.0

        self._total_acquires: int = 0
        self._total_waits: int = 0
        self._total_cooldowns: int = 0

    async def acquire(self) -> None:
        """Wait until a token is available (respects cooldown and jitter)."""
        self._total_acquires += 1

        while True:
            if self._is_in_cooldown():
                self._total_cooldowns += 1
                wait = min(0.5, self._cooldown_until - time.time())
                if wait > 0:
                    logger.debug("ProviderRateLimiter cooldown — waiting %.2fs", wait)
                    await asyncio.sleep(wait)
                continue

            self._refill()

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                jitter = random.uniform(self._jitter_min, self._jitter_max)
                if jitter > 0:
                    self._total_waits += 1
                    await asyncio.sleep(jitter)
                return

            # Not enough tokens yet — sleep a short slice and retry.
            await asyncio.sleep(0.05)

    def record_success(self) -> None:
        """Signal successful request; resets failure counter."""
        self._failure_count = 0

    def record_failure(self) -> None:
        """Signal failed request; triggers cooldown when threshold exceeded."""
        self._failure_count += 1
        logger.warning("ProviderRateLimiter: failure count=%d", self._failure_count)
        if self._failure_count >= self._cooldown_after:
            self._cooldown_until = time.time() + self._cooldown_duration
            logger.warning(
                "ProviderRateLimiter: entering cooldown for %.1fs after %d failures",
                self._cooldown_duration,
                self._failure_count,
            )

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self._tokens

    @property
    def is_in_cooldown(self) -> bool:
        return self._is_in_cooldown()

    @property
    def metrics(self) -> dict:
        return {
            "total_acquires": self._total_acquires,
            "total_waits": self._total_waits,
            "total_cooldowns": self._total_cooldowns,
            "current_tokens": self.available_tokens,
            "failure_count": self._failure_count,
            "in_cooldown": self.is_in_cooldown,
        }

    def reset(self) -> None:
        self._tokens = float(self._burst)
        self._last_refill = time.time()
        self._failure_count = 0
        self._cooldown_until = 0.0

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

    def _is_in_cooldown(self) -> bool:
        return time.time() < self._cooldown_until

    def __repr__(self) -> str:
        return (
            f"<ProviderRateLimiter rate={self._rate}/s "
            f"burst={self._burst} tokens={self.available_tokens:.1f}>"
        )


# Backward-compat alias used directly by the old providers/rate_limiter.py importers.
TokenBucketRateLimiter = ProviderRateLimiter


# =============================================================================
# BrokerRateLimiter — sync, multi-bucket, DhanHQ v2 limits
# =============================================================================

@dataclass
class RateLimit:
    """Rate limit configuration for a single bucket."""
    requests_per_second: int = 10
    requests_per_minute: int = 600
    requests_per_hour: int = 3600
    requests_per_day: int = 10000


class _TokenBucket:
    """Internal thread-safe token bucket."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens: float = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill: float = time.monotonic()
        self._lock = Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def try_consume(self, tokens: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class BrokerRateLimiter:
    """
    Multi-bucket rate limiter pre-configured for DhanHQ v2 API limits.

    Buckets:
        orders       — 10 req/s, 250 burst
        quotes       — 1 req/s
        historical   — 5 req/s
        non_trading  — 20 req/s
        option_chain — 1 every 3s (≈ 0.33 req/s)
        default      — 10 req/s

    Usage:
        limiter = BrokerRateLimiter()
        if limiter.try_request("orders"):
            await place_order()
        else:
            wait = limiter.get_wait_time("orders")
    """

    def __init__(self) -> None:
        self._buckets: Dict[str, _TokenBucket] = {}
        self._lock = Lock()
        self._setup_dhan_limits()

    def _setup_dhan_limits(self) -> None:
        # Dhan v2 post-March-2026: orders bucket burst capped at 10 (not 250)
        self._buckets["orders"] = _TokenBucket(capacity=10, refill_rate=10.0)
        self._buckets["quotes"] = _TokenBucket(capacity=1, refill_rate=1.0)
        self._buckets["historical"] = _TokenBucket(capacity=5, refill_rate=5.0)
        self._buckets["non_trading"] = _TokenBucket(capacity=20, refill_rate=20.0)
        self._buckets["option_chain"] = _TokenBucket(capacity=1, refill_rate=0.33)
        self._buckets["default"] = _TokenBucket(capacity=10, refill_rate=10.0)

    def register_bucket(self, name: str, capacity: int, refill_rate: float) -> None:
        with self._lock:
            self._buckets[name] = _TokenBucket(capacity=capacity, refill_rate=refill_rate)

    def try_request(self, bucket: str = "default") -> bool:
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        return bucket_obj.try_consume()

    def wait_for_token(self, bucket: str = "default", timeout: float = 5.0) -> bool:
        """Block until a token is available or timeout expires (synchronous)."""
        start = time.monotonic()
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        while time.monotonic() - start < timeout:
            if bucket_obj.try_consume():
                return True
            time.sleep(0.01)
        return False

    async def async_wait_for_token(self, bucket: str = "default", timeout: float = 5.0) -> bool:
        """
        Non-blocking coroutine — yields control to the event loop between checks.

        Must be awaited from an async context (replaces the blocking
        wait_for_token() in any async call path such as DhanHttpClient).

        Uses asyncio.get_running_loop() (not deprecated get_event_loop()) so
        this is safe in Python 3.10+ inside any coroutine.
        """
        loop = asyncio.get_running_loop()
        start = loop.time()
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        while loop.time() - start < timeout:
            if bucket_obj.try_consume():
                return True
            await asyncio.sleep(0.01)
        return False

    def get_wait_time(self, bucket: str = "default") -> float:
        """Estimated seconds until next token is available."""
        bucket_obj = self._buckets.get(bucket, self._buckets["default"])
        with bucket_obj._lock:
            bucket_obj._refill()
            if bucket_obj.tokens >= 1:
                return 0.0
            return (1 - bucket_obj.tokens) / bucket_obj.refill_rate


# Backward-compat alias used directly by the old token_bucket.py importers.
RateLimiter = BrokerRateLimiter


# =============================================================================
# RequestScheduler — priority queue over BrokerRateLimiter
# =============================================================================

@dataclass
class _ScheduledRequest:
    """Priority-queue entry.  Higher numeric priority = processed first."""
    priority: int
    request_id: str
    bucket: str
    callback: Callable = field(compare=False)

    def __lt__(self, other: "_ScheduledRequest") -> bool:
        return self.priority > other.priority

    def __le__(self, other: "_ScheduledRequest") -> bool:
        return self.priority >= other.priority

    def __gt__(self, other: "_ScheduledRequest") -> bool:
        return self.priority < other.priority

    def __ge__(self, other: "_ScheduledRequest") -> bool:
        return self.priority <= other.priority

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ScheduledRequest):
            return NotImplemented
        return self.priority == other.priority


class RequestScheduler:
    """
    Priority-queue scheduler built on top of BrokerRateLimiter.

    When a request is submitted:
    - If a token is immediately available the callback is invoked at once.
    - Otherwise the request is queued and processed (in priority order)
      on the next call to process_pending().

    Usage:
        scheduler = RequestScheduler(BrokerRateLimiter())
        scheduler.submit("req1", "orders", priority=5, callback=my_fn)
        scheduler.process_pending()  # drain queued requests
    """

    def __init__(self, rate_limiter: BrokerRateLimiter) -> None:
        self._rl = rate_limiter
        self._heap: list = []
        self._lock = Lock()

    def submit(
        self,
        request_id: str,
        bucket: str,
        callback: Callable,
        priority: int = 0,
    ) -> bool:
        """
        Submit a request.  Calls callback immediately if a token is available,
        otherwise queues it.

        Returns True if executed immediately, False if queued.
        """
        if self._rl.try_request(bucket):
            callback()
            return True

        with self._lock:
            heapq.heappush(
                self._heap,
                _ScheduledRequest(
                    priority=priority,
                    request_id=request_id,
                    bucket=bucket,
                    callback=callback,
                ),
            )
        return False

    def process_pending(self) -> int:
        """
        Drain the pending queue, executing callbacks in priority order as
        tokens become available.

        Returns the number of requests successfully executed.
        """
        executed = 0
        with self._lock:
            remaining = []
            while self._heap:
                req = heapq.heappop(self._heap)
                if self._rl.try_request(req.bucket):
                    req.callback()
                    executed += 1
                else:
                    remaining.append(req)
            for req in remaining:
                heapq.heappush(self._heap, req)
        return executed

    @property
    def pending_count(self) -> int:
        return len(self._heap)


__all__ = [
    "ProviderRateLimiter",
    "BrokerRateLimiter",
    "RequestScheduler",
    "TokenBucketRateLimiter",
    "RateLimiter",
    "RateLimit",
]
