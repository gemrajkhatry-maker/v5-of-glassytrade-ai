"""Tests for LLM Circuit Breaker."""

import time
import pytest
from app.core.llm_circuit_breaker import LLMCircuitBreaker, CircuitState


class TestLLMCircuitBreakerInitialState:
    """Test initial state of circuit breaker."""

    def test_starts_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = LLMCircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed is True
        assert cb.is_open is False
        assert cb.is_half_open is False

    def test_allows_call_when_closed(self):
        """Should allow calls when circuit is closed."""
        cb = LLMCircuitBreaker()
        assert cb.should_allow_call() is True

    def test_custom_thresholds(self):
        """Should support custom failure threshold and recovery timeout."""
        cb = LLMCircuitBreaker(failure_threshold=5, recovery_timeout=120.0)
        assert cb._failure_threshold == 5
        assert cb._recovery_timeout == 120.0


class TestLLMCircuitBreakerTransitions:
    """Test state transitions."""

    def test_opens_after_threshold_failures(self):
        """Circuit should open after failure_threshold consecutive failures."""
        cb = LLMCircuitBreaker(failure_threshold=3)
        
        # Record failures up to threshold
        cb.record_failure()
        assert cb.is_closed is True  # Still closed
        
        cb.record_failure()
        assert cb.is_closed is True  # Still closed
        
        cb.record_failure()
        assert cb.is_open is True  # Now open!
        assert cb.should_allow_call() is False

    def test_half_open_after_recovery_timeout(self):
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        
        # Wait for recovery timeout
        time.sleep(1.1)
        
        # Should be half-open now
        assert cb.is_half_open is True
        assert cb.should_allow_call() is True  # Allow test call

    def test_closes_on_success_from_half_open(self):
        """Circuit should close on successful call from HALF_OPEN."""
        cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=0.5)
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        
        # Wait for recovery timeout
        time.sleep(0.6)
        assert cb.is_half_open is True
        
        # Record success
        cb.record_success()
        assert cb.is_closed is True
        assert cb.should_allow_call() is True

    def test_opens_on_failure_from_half_open(self):
        """Circuit should re-open on failed call from HALF_OPEN."""
        cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=0.5)
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        
        # Wait for recovery timeout
        time.sleep(0.6)
        assert cb.is_half_open is True
        
        # Record failure
        cb.record_failure()
        assert cb.is_open is True
        assert cb.should_allow_call() is False


class TestLLMCircuitBreakerFallback:
    """Test fallback decision generation."""

    def test_fallback_returns_flat(self):
        """Fallback decision should be FLAT (no trade)."""
        cb = LLMCircuitBreaker()
        fallback = cb.get_fallback_decision()
        
        assert fallback["direction"] == "FLAT"
        assert fallback["confidence"] == "Low"
        assert fallback["is_fallback"] is True
        assert "circuit breaker" in fallback["rationale"].lower()

    def test_fallback_tracks_metrics(self):
        """Fallback calls should be tracked in metrics."""
        cb = LLMCircuitBreaker()
        
        cb.get_fallback_decision()
        cb.get_fallback_decision()
        
        metrics = cb.get_metrics()
        assert metrics["total_fallbacks"] == 2


class TestLLMCircuitBreakerMetrics:
    """Test metrics collection."""

    def test_tracks_calls_and_failures(self):
        """Should track total calls and failures."""
        cb = LLMCircuitBreaker()
        
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        cb.record_success()
        
        metrics = cb.get_metrics()
        assert metrics["total_calls"] == 4
        assert metrics["total_failures"] == 1
        assert metrics["failure_rate"] == 0.25

    def test_resets_failure_count_on_success(self):
        """Success should reset consecutive failure count."""
        cb = LLMCircuitBreaker(failure_threshold=3)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Should reset count
        
        cb.record_failure()
        cb.record_failure()
        assert cb.is_closed is True  # Should still be closed (count reset)


class TestLLMCircuitBreakerReset:
    """Test manual reset functionality."""

    def test_reset_returns_to_closed(self):
        """Reset should return circuit to CLOSED state."""
        cb = LLMCircuitBreaker(failure_threshold=2)
        
        # Open the circuit
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        
        # Reset
        cb.reset()
        assert cb.is_closed is True
        assert cb.should_allow_call() is True

    def test_reset_clears_failure_count(self):
        """Reset should clear failure count."""
        cb = LLMCircuitBreaker(failure_threshold=2)
        
        cb.record_failure()
        cb.record_failure()
        cb.reset()
        
        # Should need 2 more failures to open
        cb.record_failure()
        assert cb.is_closed is True


class TestLLMCircuitBreakerThreadSafety:
    """Test thread safety."""

    def test_concurrent_calls(self):
        """Should handle concurrent calls safely."""
        import concurrent.futures
        import threading
        
        cb = LLMCircuitBreaker(failure_threshold=100)
        errors = []
        
        def record_operations():
            try:
                for _ in range(100):
                    cb.record_success()
                    cb.should_allow_call()
                    cb.get_metrics()
            except Exception as e:
                errors.append(e)
        
        # Run multiple threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(record_operations) for _ in range(10)]
            concurrent.futures.wait(futures)
        
        # Should have no errors
        assert len(errors) == 0
