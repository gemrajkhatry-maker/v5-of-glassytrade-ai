"""Adaptive circuit breaker for trading risk management."""

import time
from dataclasses import dataclass
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    timeout_seconds: int = 300
    half_open_max_calls: int = 3


class AdaptiveCircuitBreaker:
    """Self-healing circuit breaker with adaptive thresholds."""
    
    def __init__(self, config: CircuitBreakerConfig | None = None):
        self.config = config or CircuitBreakerConfig()
        self._failure_count = 0
        self._success_count = 0
        self._state = CircuitState.CLOSED
        self._last_failure_time = 0.0
        self._half_open_calls = 0
    
    @property
    def state(self) -> CircuitState:
        return self._state
    
    @property
    def is_open(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return False
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.config.timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                return False
            return True
        return False
    
    def record_success(self) -> None:
        """Record a successful operation."""
        self._failure_count = max(0, self._failure_count - 1)
        self._success_count += 1
        
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.config.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
    
    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            return
        
        if self._failure_count >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
    
    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
    
    def get_metrics(self) -> dict:
        """Return circuit breaker metrics."""
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
        }


# Global circuit breakers for key components
_session_circuit = AdaptiveCircuitBreaker(CircuitBreakerConfig(
    failure_threshold=3,
    timeout_seconds=300,
))

_amt_circuit = AdaptiveCircuitBreaker(CircuitBreakerConfig(
    failure_threshold=5,
    timeout_seconds=120,
))

_position_circuit = AdaptiveCircuitBreaker(CircuitBreakerConfig(
    failure_threshold=3,
    timeout_seconds=600,
))


def get_session_circuit() -> AdaptiveCircuitBreaker:
    return _session_circuit


def get_amt_circuit() -> AdaptiveCircuitBreaker:
    return _amt_circuit


def get_position_circuit() -> AdaptiveCircuitBreaker:
    return _position_circuit