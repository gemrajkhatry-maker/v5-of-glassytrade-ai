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

State/transition logic delegates to `shared.resilience.CircuitBreaker`
(single source of truth); this module keeps the LLM-specific public API
(enum, fallback decision, extended metrics).
"""

from __future__ import annotations

import logging
import threading
from enum import Enum

from shared.resilience import CircuitBreaker

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
        # success_threshold=1 → a single successful call re-closes from HALF_OPEN,
        # matching the LLM breaker's historical one-success-close semantics.
        self._breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=1,
        )

        # Metrics not tracked by the shared CircuitBreaker
        self._metrics_lock = threading.Lock()
        self._total_calls = 0
        self._total_failures = 0
        self._total_fallbacks = 0

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return CircuitState(self._breaker.state.value)

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
        with self._metrics_lock:
            self._total_calls += 1
        self._breaker.record_success()

    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed LLM call."""
        with self._metrics_lock:
            self._total_calls += 1
            self._total_failures += 1
        self._breaker.record_failure()

    def should_allow_call(self) -> bool:
        """Check if LLM call should be allowed.

        Returns:
            True if call should proceed, False if should use fallback
        """
        return self._breaker.can_execute()

    def get_fallback_decision(self) -> dict:
        """Get fallback decision when circuit is open.

        Returns a conservative FLAT decision to avoid trading without LLM validation.
        """
        with self._metrics_lock:
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
        breaker_metrics = self._breaker.get_metrics()
        with self._metrics_lock:
            return {
                "state": breaker_metrics["state"],
                "failure_count": breaker_metrics["failure_count"],
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "total_fallbacks": self._total_fallbacks,
                "failure_rate": self._total_failures / max(self._total_calls, 1),
            }

    def reset(self) -> None:
        """Reset circuit breaker to initial state."""
        self._breaker.reset()
        with self._metrics_lock:
            self._total_calls = 0
            self._total_failures = 0
            self._total_fallbacks = 0
        logger.info("LLM circuit breaker: Reset to CLOSED")
