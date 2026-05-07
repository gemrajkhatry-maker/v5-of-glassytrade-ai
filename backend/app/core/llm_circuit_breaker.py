"""LLM Circuit Breaker — prevents cascading LLM failures.

Implements the circuit breaker pattern for LLM calls:
- CLOSED: Normal operation, calls pass through
- OPEN: LLM failing, fast-fail with fallback
- HALF_OPEN: Testing if LLM recovered

Transitions:
- CLOSED → OPEN: After `failure_threshold` consecutive failures
- OPEN → HALF_OPEN: After `recovery_timeout` seconds
- HALF_OPEN → CLOSED: After successful call
- HALF_OPEN → OPEN: After failed call
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from threading import Lock

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, fast-fail
    HALF_OPEN = "half_open"  # Testing recovery


class LLMCircuitBreaker:
    """Circuit breaker for LLM inference calls.
    
    Protects the system from cascading LLM failures by:
    1. Fast-failing when LLM is down (no waiting for timeout)
    2. Automatically testing recovery
    3. Providing fallback signal when circuit is open
    """
    
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
    ):
        """
        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = Lock()
        
        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_fallbacks = 0
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        with self._lock:
            self._check_state_transition()
            return self._state
    
    @property
    def is_closed(self) -> bool:
        """Circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Circuit is open (fast-fail, use fallback)."""
        return self.state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Circuit is half-open (testing recovery)."""
        return self.state == CircuitState.HALF_OPEN
    
    def record_success(self) -> None:
        """Record a successful LLM call."""
        with self._lock:
            self._total_calls += 1
            self._failure_count = 0
            
            if self._state == CircuitState.HALF_OPEN:
                logger.info("LLM circuit breaker: HALF_OPEN → CLOSED (recovery confirmed)")
                self._state = CircuitState.CLOSED
    
    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed LLM call."""
        with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                logger.warning("LLM circuit breaker: HALF_OPEN → OPEN (recovery failed)")
                self._state = CircuitState.OPEN
            elif self._failure_count >= self._failure_threshold:
                logger.error(
                    "LLM circuit breaker: CLOSED → OPEN "
                    "(%d consecutive failures, threshold=%d)",
                    self._failure_count,
                    self._failure_threshold,
                )
                self._state = CircuitState.OPEN
    
    def should_allow_call(self) -> bool:
        """Check if LLM call should be allowed.
        
        Returns:
            True if call should proceed, False if should use fallback
        """
        with self._lock:
            self._check_state_transition()
            
            if self._state == CircuitState.CLOSED:
                return True
            elif self._state == CircuitState.OPEN:
                return False
            else:  # HALF_OPEN
                return True  # Allow one test call
    
    def get_fallback_decision(self) -> dict:
        """Get fallback decision when circuit is open.
        
        Returns a conservative FLAT decision to avoid trading without LLM validation.
        """
        with self._lock:
            self._total_fallbacks += 1
        
        logger.warning("LLM circuit breaker: Using fallback decision (circuit OPEN)")
        return {
            "direction": "FLAT",
            "rationale": "LLM service unavailable — circuit breaker open. Using conservative fallback (no trade).",
            "confidence": "Low",
            "input_prompt": "[FALLBACK: Circuit Breaker Open] LLM service is failing. Using rule-based fallback.",
            "raw_output": "CIRCUIT_BREAKER_FALLBACK",
            "market_state": "BALANCED",  # Conservative assumption
            "is_fallback": True,
        }
    
    def get_metrics(self) -> dict:
        """Get circuit breaker metrics."""
        with self._lock:
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "total_fallbacks": self._total_fallbacks,
                "failure_rate": self._total_failures / max(self._total_calls, 1),
            }
    
    def reset(self) -> None:
        """Reset circuit breaker to initial state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            logger.info("LLM circuit breaker: Reset to CLOSED")
    
    def _check_state_transition(self) -> None:
        """Check if state should transition (must be called with lock held)."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                logger.info(
                    "LLM circuit breaker: OPEN → HALF_OPEN "
                    "(recovery timeout elapsed: %.0fs)",
                    elapsed,
                )
                self._state = CircuitState.HALF_OPEN
