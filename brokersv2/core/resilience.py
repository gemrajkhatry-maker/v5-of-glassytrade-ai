"""
Circuit Breaker - Fault tolerance pattern for resilient systems.

Protects against cascading failures in distributed systems by:
- Detecting repeated failures
- Opening circuit to reject requests
- Allowing recovery via half-open state
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from threading import RLock
from typing import Optional

from brokersv2.core.constants import CircuitBreaker as CBConstants
from brokersv2.core.errors import CircuitBreakerOpenError

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Rejecting requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.
    
    State machine:
    CLOSED → (failures >= threshold) → OPEN
    OPEN → (timeout elapsed) → HALF_OPEN
    HALF_OPEN → (success) → CLOSED
    HALF_OPEN → (failure) → OPEN
    
    Thread-safe with RLock.
    
    Usage:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        
        try:
            with cb:
                result = risky_operation()
        except CircuitBreakerOpenError:
            logger.error("Circuit breaker open, request rejected")
        except Exception as e:
            logger.error(f"Operation failed: {e}")
    """
    
    def __init__(
        self,
        failure_threshold: int = CBConstants.FAILURE_THRESHOLD,
        recovery_timeout: float = CBConstants.RECOVERY_TIMEOUT,
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._total_requests = 0
        self._last_failure_time: Optional[float] = None
        
        self._lock = RLock()
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        with self._lock:
            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitState.OPEN and self._should_attempt_recovery():
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker transitioning to HALF_OPEN")
            return self._state
    
    @property
    def failure_count(self) -> int:
        """Current failure count."""
        return self._failure_count
    
    @property
    def success_count(self) -> int:
        """Total success count."""
        return self._success_count
    
    @property
    def total_requests(self) -> int:
        """Total request count."""
        return self._total_requests
    
    def __enter__(self):
        """Enter circuit breaker context."""
        self._check_state()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit circuit breaker context, record success/failure."""
        with self._lock:
            self._total_requests += 1
            
            if exc_type is None:
                # Success
                self._success_count += 1
                self._on_success()
            else:
                # Failure (only count if it's not CircuitBreakerOpenError)
                if exc_type != CircuitBreakerOpenError:
                    self._failure_count += 1
                    self._last_failure_time = time.monotonic()
                    self._on_failure()
        
        # Don't suppress exceptions
        return False
    
    def _check_state(self):
        """Check if request is allowed in current state."""
        current_state = self.state  # This handles OPEN → HALF_OPEN transition
        
        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN (failures={self._failure_count}, "
                f"threshold={self._failure_threshold})"
            )
    
    def _on_success(self):
        """Handle successful request."""
        if self._state == CircuitState.HALF_OPEN:
            # Recovery successful, close circuit
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            logger.info("Circuit breaker CLOSED after successful recovery")
    
    def _on_failure(self):
        """Handle failed request."""
        if self._state == CircuitState.HALF_OPEN:
            # Recovery failed, reopen circuit
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
            logger.warning("Circuit breaker re-OPENED after failed recovery")
        elif self._failure_count >= self._failure_threshold:
            # Threshold reached, open circuit
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
            logger.warning(
                f"Circuit breaker OPENED (failures={self._failure_count})"
            )
    
    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return True
        
        elapsed = time.monotonic() - self._last_failure_time
        return elapsed >= self._recovery_timeout
    
    def reset(self):
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._total_requests = 0
            self._last_failure_time = None
            logger.info("Circuit breaker manually reset")
    
    def get_state_info(self) -> dict:
        """Get detailed state information for monitoring."""
        with self._lock:
            return {
                "state": self.state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_requests": self._total_requests,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
                "last_failure_time": self._last_failure_time,
            }
