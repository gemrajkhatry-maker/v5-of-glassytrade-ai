"""Adaptive circuit breaker for trading risk management.

NOTE: This module is kept for backward compatibility. All new code should use
the unified CircuitBreaker from shared.resilience. This module delegates to
shared.resilience.CircuitBreaker for actual implementation.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from shared.resilience import (
    CircuitBreaker as _UnifiedCircuitBreaker,
    CircuitState as _UnifiedCircuitState,
)
from shared.resilience import CircuitState

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker - maps to shared.resilience.CircuitBreakerConfig."""
    failure_threshold: int = 5
    timeout_seconds: int = 300  # maps to recovery_timeout
    half_open_max_calls: int = 3  # maps to success_threshold


class AdaptiveCircuitBreaker:
    """Backward compatibility wrapper around shared.resilience.CircuitBreaker.

    Provides the same API as the original AdaptiveCircuitBreaker but delegates
    to the unified CircuitBreaker implementation in shared.resilience.
    """

    def __init__(self, config: CircuitBreakerConfig | None = None):
        cfg = config or CircuitBreakerConfig()
        self._delegate = _UnifiedCircuitBreaker(
            failure_threshold=cfg.failure_threshold,
            recovery_timeout=float(cfg.timeout_seconds),
            success_threshold=cfg.half_open_max_calls,
        )
        # For backward compatibility
        self.config = cfg
        self._failure_count = 0
        self._success_count = 0
        self._state = CircuitState.CLOSED
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        # Update our cached state from delegate
        delegate_state = self._delegate.state
        self._state = delegate_state  # type: ignore
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def record_success(self) -> None:
        """Record a successful operation."""
        self._delegate.record_success()
        # Update cached counts for backward compatibility
        self._failure_count = self._delegate.failure_count
        self._success_count = getattr(self._delegate, '_success_count', 0)

    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed operation."""
        self._delegate.record_failure()
        # Update cached counts for backward compatibility
        self._failure_count = self._delegate.failure_count
        self._success_count = getattr(self._delegate, '_success_count', 0)
        self._last_failure_time = time.time()

    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self._delegate.reset()
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._state = CircuitState.CLOSED

    def get_metrics(self) -> dict:
        """Return circuit breaker metrics."""
        metrics = self._delegate.get_metrics()
        # Map to old API format
        return {
            "state": metrics["state"],
            "failure_count": metrics["failure_count"],
            "success_count": metrics["success_count"],
            "last_failure_time": metrics["last_failure_time"],
        }


# Global circuit breakers for key components
_session_circuit = AdaptiveCircuitBreaker(None)  # Uses defaults
_amt_circuit = AdaptiveCircuitBreaker(None)      # Uses defaults
_position_circuit = AdaptiveCircuitBreaker(None) # Uses defaults


def get_session_circuit() -> AdaptiveCircuitBreaker:
    return _session_circuit


def get_amt_circuit() -> AdaptiveCircuitBreaker:
    return _amt_circuit


def get_position_circuit() -> AdaptiveCircuitBreaker:
    return _position_circuit