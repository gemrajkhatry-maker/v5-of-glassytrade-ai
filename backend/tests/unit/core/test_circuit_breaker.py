"""Tests for circuit breaker module."""

import pytest
from app.core.circuit_breaker import (
    AdaptiveCircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        """Test initial state is CLOSED."""
        cb = AdaptiveCircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open

    def test_record_success_decrements_failure(self):
        """Test success decrements failure count."""
        cb = AdaptiveCircuitBreaker()
        cb.record_failure(Exception("test"))
        assert cb._failure_count == 1
        cb.record_success()
        assert cb._failure_count == 0

    def test_record_failure_opens_circuit(self):
        """Test circuit opens after threshold failures."""
        cb = AdaptiveCircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            cb.record_failure(Exception("test"))
        assert cb.state == CircuitState.OPEN
        assert cb.is_open

    def test_half_open_after_timeout(self):
        """Test circuit enters HALF_OPEN after timeout."""
        import time
        cb = AdaptiveCircuitBreaker(CircuitBreakerConfig(failure_threshold=1, timeout_seconds=0.1))
        cb.record_failure(Exception("test"))
        time.sleep(0.15)
        assert not cb.is_open  # Should be HALF_OPEN now

    def test_get_metrics(self):
        """Test metrics retrieval."""
        cb = AdaptiveCircuitBreaker()
        cb.record_failure(Exception("test"))
        metrics = cb.get_metrics()
        assert metrics["state"] == "closed"
        assert metrics["failure_count"] == 1
        assert metrics["success_count"] == 0


class TestCircuitBreakerInstances:
    """Test global circuit breaker instances."""
    
    def test_get_session_circuit(self):
        from app.core.circuit_breaker import get_session_circuit
        cb = get_session_circuit()
        assert isinstance(cb, AdaptiveCircuitBreaker)

    def test_get_amt_circuit(self):
        from app.core.circuit_breaker import get_amt_circuit
        cb = get_amt_circuit()
        assert isinstance(cb, AdaptiveCircuitBreaker)

    def test_get_position_circuit(self):
        from app.core.circuit_breaker import get_position_circuit
        cb = get_position_circuit()
        assert isinstance(cb, AdaptiveCircuitBreaker)