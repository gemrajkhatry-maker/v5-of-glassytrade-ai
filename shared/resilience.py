"""
Unified resilience primitives for GlassyTrade AI.
"""

import time
import asyncio
import logging
from typing import TypeVar, Awaitable, Callable, Optional, Dict
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

T = TypeVar('T')

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreakerError(Exception):
    pass

@dataclass
class CircuitBreakerConfig:
    """
    Configuration for circuit breaker.
    """
    failure_threshold: int = 5
    success_threshold: int = 3
    recovery_timeout: float = 60.0 # renamed from timeout for consistency

class CircuitBreaker:
    """
    Unified circuit breaker supporting both sync and async patterns.
    """
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()
        self._sync_lock = __import__('threading').Lock()

    @property
    def state(self) -> CircuitState:
        with self._sync_lock:
            self._check_and_transition()
            return self._state

    def _check_and_transition(self):
        if self._state == CircuitState.OPEN and self._last_failure_time:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

    def record_success(self):
        with self._sync_lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
            else:
                self._failure_count = 0

    def record_failure(self):
        with self._sync_lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            logger.debug(
                "CircuitBreaker failure recorded: count=%d, threshold=%d, state=%s",
                self._failure_count, self.failure_threshold, self._state
            )
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("CircuitBreaker opened: %s", self)

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        with self._sync_lock:
            self._check_and_transition()
            return self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def __enter__(self):
        with self._sync_lock:
            self._check_and_transition()
            if self._state == CircuitState.OPEN:
                raise CircuitBreakerError("Circuit breaker is open")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()
        return False

    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerError("Circuit breaker is open")
        try:
            result = await operation()
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

class PerEntityCircuitBreaker:
    """
    Manages multiple circuit breakers keyed by entity (e.g., Symbol).
    Consolidates logic from TradingEngine's SymbolCircuitBreaker.
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._breakers: Dict[str, CircuitBreaker] = {}

    def _get_breaker(self, key: str) -> CircuitBreaker:
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout
            )
        return self._breakers[key]

    def record_failure(self, key: str):
        self._get_breaker(key).record_failure()

    def record_success(self, key: str):
        self._get_breaker(key).record_success()

    def is_open(self, key: str) -> bool:
        return self._get_breaker(key).state == CircuitState.OPEN
