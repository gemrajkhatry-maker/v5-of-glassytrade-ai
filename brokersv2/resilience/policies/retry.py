"""
Canonical retry policy — single source of truth for all retry behavior.

Absorbs both:
- infrastructure/retry_manager.py  (RetryPolicy + RetryManager taking a callable/coroutine)
- gateway/retry_manager.py         (RetryConfig + RetryManager taking func + *args/**kwargs)

Public API:
    # Configuration
    policy = RetryPolicy(max_retries=3, base_delay=1.0)

    # Async execution — pass a zero-argument async factory so fresh coroutines
    # are produced on each attempt (avoids the "can't re-await a spent coroutine"
    # trap from the old infrastructure version):
    result = await RetryManager(policy).execute(lambda: my_async_func(arg))

    # Sync execution:
    result = RetryManager(policy).execute_sync(lambda: my_sync_func(arg))

    # Gateway-style: func + args (backward compat helper)
    result = await RetryManager(policy).execute_with_args(my_async_func, arg1, kw=val)

Backward-compat re-exports live in:
    brokersv2/infrastructure/retry_manager.py
    brokersv2/gateway/retry_manager.py
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Set, Tuple, Type

logger = logging.getLogger(__name__)


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        super().__init__(message)
        self.last_exception = last_exception


@dataclass
class RetryMetrics:
    """Cumulative retry statistics for a RetryManager instance."""
    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    total_retries: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.successful_attempts / self.total_attempts

    @property
    def retry_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.total_retries / self.total_attempts


@dataclass
class RetryPolicy:
    """
    Unified retry configuration.

    Compatible with both former RetryPolicy (infrastructure) and
    RetryConfig (gateway) field names.  All former fields are present
    so existing call sites that construct either class by keyword work
    without changes.
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0

    # Jitter — gateway used jitter_enabled; infrastructure used jitter (bool).
    # We expose both names; jitter_enabled takes precedence if set explicitly.
    jitter: bool = True
    jitter_enabled: bool = True
    jitter_factor: float = 0.1

    # Retryable exceptions — infrastructure used a Tuple, gateway used a Set.
    # We accept either at construction time and normalise to a frozenset.
    retryable_exceptions: Any = field(
        default_factory=lambda: frozenset({ConnectionError, TimeoutError, OSError})
    )

    log_retries: bool = True
    circuit_breaker: Optional[Any] = None
    metrics: RetryMetrics = field(default_factory=RetryMetrics)

    def __post_init__(self) -> None:
        # Normalise retryable_exceptions to a frozenset of exception types.
        if isinstance(self.retryable_exceptions, (tuple, list, set, frozenset)):
            self.retryable_exceptions = frozenset(self.retryable_exceptions)
        else:
            self.retryable_exceptions = frozenset({self.retryable_exceptions})

        # Keep jitter and jitter_enabled in sync (jitter_enabled wins).
        self.jitter = self.jitter_enabled

    def should_retry(self, exc: Exception) -> bool:
        """Return True if the exception type is in the retryable set."""
        return isinstance(exc, tuple(self.retryable_exceptions))

    def calculate_delay(self, attempt: int) -> float:
        """Exponential backoff with optional jitter, capped at max_delay."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        if self.jitter:
            delay += delay * self.jitter_factor * random.random()
        return min(delay, self.max_delay)


class RetryManager:
    """
    Executes operations with retry semantics defined by a RetryPolicy.

    Three execution styles are supported:

    1.  execute(factory)
        factory is a zero-argument callable returning a coroutine (async) or
        a plain value (sync).  A fresh call is made on every attempt.

    2.  execute_with_args(func, *args, **kwargs)
        Gateway-style: the manager calls func(*args, **kwargs) on each attempt.

    3.  execute_sync(factory)
        Same as execute() but for synchronous callables, using time.sleep.
    """

    def __init__(
        self,
        policy: Optional[RetryPolicy] = None,
        default_policy: Optional[RetryPolicy] = None,
        config: Optional[RetryPolicy] = None,
    ):
        # Accept policy / default_policy (infra compat) / config (gateway compat).
        self._policy = policy or default_policy or config or RetryPolicy()
        self._last_exception: Optional[Exception] = None
        self._retry_count: int = 0
        self._total_retries: int = 0

    # ------------------------------------------------------------------
    # Primary async interface
    # ------------------------------------------------------------------

    async def execute(
        self,
        factory: Callable[[], Any],
        policy: Optional[RetryPolicy] = None,
    ) -> Any:
        """
        Execute factory() with retry.

        factory must be a zero-argument callable that produces a fresh
        coroutine on every call (or returns a plain value for sync ops).
        """
        pol = policy or self._policy
        last_exc: Optional[Exception] = None

        for attempt in range(pol.max_retries + 1):
            pol.metrics.total_attempts += 1

            try:
                if pol.circuit_breaker and not pol.circuit_breaker.allow_request():
                    raise RetryExhaustedError(
                        "Circuit breaker is OPEN — request blocked",
                        last_exception=last_exc,
                    )

                result = factory()
                if asyncio.iscoroutine(result):
                    result = await result

                pol.metrics.successful_attempts += 1
                if attempt > 0:
                    pol.metrics.total_retries += attempt
                    if pol.log_retries:
                        logger.info("Operation succeeded after %d retries", attempt)

                if pol.circuit_breaker:
                    pol.circuit_breaker.record_success()

                self._retry_count = attempt
                return result

            except RetryExhaustedError:
                raise
            except Exception as exc:
                last_exc = exc
                self._last_exception = exc
                pol.metrics.failed_attempts += 1

                if not pol.should_retry(exc):
                    logger.error("Non-retryable error: %s: %s", type(exc).__name__, exc)
                    raise

                if attempt >= pol.max_retries:
                    if pol.circuit_breaker:
                        pol.circuit_breaker.record_failure()
                    self._retry_count = attempt
                    raise RetryExhaustedError(
                        f"Max retries ({pol.max_retries}) exceeded",
                        last_exception=exc,
                    )

                delay = pol.calculate_delay(attempt)
                if pol.log_retries:
                    logger.warning(
                        "Attempt %d/%d failed: %s: %s. Retrying in %.2fs…",
                        attempt + 1,
                        pol.max_retries + 1,
                        type(exc).__name__,
                        exc,
                        delay,
                    )
                await asyncio.sleep(delay)
                self._total_retries += 1

        raise RetryExhaustedError("Unexpected retry exhaustion", last_exception=last_exc)

    # Gateway-style compat: func + *args/**kwargs
    async def execute_with_retry(
        self,
        func: Callable[..., Any],
        *args: Any,
        policy: Optional[RetryPolicy] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute async func(*args, **kwargs) with retry.

        The ``policy`` keyword is consumed by the retry manager and is NOT
        forwarded to ``func``.  This preserves compatibility with both:
        - infrastructure style: execute_with_retry(coro_factory, policy=policy)
        - gateway style:        execute_with_retry(func, arg1, arg2)

        On exhaustion, re-raises the **original** last exception (gateway compat)
        rather than wrapping it in RetryExhaustedError.
        """
        try:
            return await self.execute(lambda: func(*args, **kwargs), policy=policy)
        except RetryExhaustedError as exc:
            if exc.last_exception is not None:
                raise exc.last_exception from exc
            raise

    # Alias used by infrastructure callers that pass a pre-built coroutine/callable.
    async def execute_with_retry_operation(
        self,
        operation: Any,
        policy: Optional[RetryPolicy] = None,
    ) -> Any:
        """
        Infrastructure compat: operation is a callable or already-created coroutine.

        Warning: passing a pre-created coroutine means only the first attempt will
        actually run — subsequent retries cannot re-invoke it.  Prefer wrapping in a
        lambda: ``execute(lambda: my_coro_func())``.
        """
        if callable(operation):
            return await self.execute(operation, policy=policy)
        # Bare coroutine: can only run once; no retry possible.
        return await operation

    # ------------------------------------------------------------------
    # Sync interface
    # ------------------------------------------------------------------

    def execute_sync(
        self,
        factory: Callable[[], Any],
        policy: Optional[RetryPolicy] = None,
    ) -> Any:
        """Execute factory() synchronously with retry and time.sleep backoff."""
        pol = policy or self._policy
        last_exc: Optional[Exception] = None

        for attempt in range(pol.max_retries + 1):
            pol.metrics.total_attempts += 1
            try:
                result = factory()
                pol.metrics.successful_attempts += 1
                if attempt > 0:
                    pol.metrics.total_retries += attempt
                self._retry_count = attempt
                return result
            except Exception as exc:
                last_exc = exc
                self._last_exception = exc
                pol.metrics.failed_attempts += 1

                if not pol.should_retry(exc):
                    raise

                if attempt >= pol.max_retries:
                    raise RetryExhaustedError(
                        f"Max retries ({pol.max_retries}) exceeded",
                        last_exception=exc,
                    )

                delay = pol.calculate_delay(attempt)
                if pol.log_retries:
                    logger.warning(
                        "Sync attempt %d/%d failed: %s. Retrying in %.2fs…",
                        attempt + 1,
                        pol.max_retries + 1,
                        exc,
                        delay,
                    )
                time.sleep(delay)
                self._total_retries += 1

        raise RetryExhaustedError("Unexpected sync retry exhaustion", last_exception=last_exc)

    def execute_with_retry_sync(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Gateway compat: synchronous func(*args, **kwargs) with retry."""
        return self.execute_sync(lambda: func(*args, **kwargs))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def retry_count(self) -> int:
        """Retry count of the most recent execution."""
        return self._retry_count

    @property
    def total_retries(self) -> int:
        """Cumulative retries across all executions."""
        return self._total_retries

    @property
    def last_exception(self) -> Optional[Exception]:
        return self._last_exception

    def get_metrics(self) -> RetryMetrics:
        return self._policy.metrics

    def reset_stats(self) -> None:
        self._retry_count = 0
        self._total_retries = 0
        self._last_exception = None


__all__ = [
    "RetryPolicy",
    "RetryManager",
    "RetryExhaustedError",
    "RetryMetrics",
]
