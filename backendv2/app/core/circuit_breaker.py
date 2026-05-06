"""CircuitBreaker — adaptive circuit breaker for trading risk management.

Extracted from core_components.py to enable dependency injection and testing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class CircuitState(Enum):
    """State of the circuit breaker."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5
    timeout_seconds: float = 300.0  # 5 minutes
    success_threshold: int = 3


class CircuitBreaker:
    """Adaptive circuit breaker for trading risk management.
    
    States:
    - CLOSED: Normal operation, tracking failures
    - OPEN: Circuit tripped, blocking calls
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(self, config: CircuitBreakerConfig | None = None):
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
    
    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning to HALF_OPEN if timeout elapsed."""
        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self._last_failure_time > self._config.timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
        return self._state
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        return self.state == CircuitState.OPEN
    
    def record_success(self) -> None:
        """Record a successful call."""
        self._failure_count = 0
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._success_count = 0
    
    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
    
    def __call__(self, func):
        """Decorator for circuit breaker.
        
        Wraps async functions to automatically track failures and block calls.
        """
        import asyncio
        
        async def wrapper(*args, **kwargs):
            if self.is_open:
                raise RuntimeError("Circuit breaker is OPEN")
            try:
                result = await func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise
        
        return wrapper
