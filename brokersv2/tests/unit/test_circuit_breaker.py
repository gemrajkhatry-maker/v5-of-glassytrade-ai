"""Tests for Circuit Breaker."""

import pytest
import time
from threading import Thread

from brokersv2.core.resilience import CircuitBreaker, CircuitState
from brokersv2.core.errors import CircuitBreakerOpenError


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_closed(self):
        """Test circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_successful_request_keeps_closed(self):
        """Test successful requests keep circuit closed."""
        cb = CircuitBreaker(failure_threshold=3)
        
        for _ in range(10):
            with cb:
                pass  # Simulate successful request
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failure_count_increments(self):
        """Test failure count increments on errors."""
        cb = CircuitBreaker(failure_threshold=3)
        
        for i in range(2):
            try:
                with cb:
                    raise ValueError("Test error")
            except ValueError:
                pass
        
        assert cb.failure_count == 2
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        """Test circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        
        for i in range(3):
            try:
                with cb:
                    raise ValueError("Test error")
            except ValueError:
                pass
        
        assert cb.state == CircuitState.OPEN

    def test_rejects_when_open(self):
        """Test circuit breaker rejects requests when open."""
        cb = CircuitBreaker(failure_threshold=2)
        
        # Trip the breaker
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("Error")
            except ValueError:
                pass
        
        assert cb.state == CircuitState.OPEN
        
        # Should raise CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            with cb:
                pass

    def test_half_open_after_recovery_timeout(self):
        """Test circuit transitions to HALF_OPEN after timeout."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        
        # Trip the breaker
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("Error")
            except ValueError:
                pass
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.15)
        
        # Next request should be allowed (HALF_OPEN)
        try:
            with cb:
                pass  # Simulate successful request
        except CircuitBreakerOpenError:
            pytest.fail("Should have allowed request in HALF_OPEN state")

    def test_closes_on_success_in_half_open(self):
        """Test circuit closes on successful request in HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        
        # Trip the breaker
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("Error")
            except ValueError:
                pass
        
        time.sleep(0.15)
        
        # Successful request in HALF_OPEN should close circuit
        with cb:
            pass
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_reopens_on_failure_in_half_open(self):
        """Test circuit reopens on failed request in HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        
        # Trip the breaker
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("Error")
            except ValueError:
                pass
        
        time.sleep(0.15)
        
        # Failed request in HALF_OPEN should reopen circuit
        try:
            with cb:
                raise ValueError("Error in HALF_OPEN")
        except ValueError:
            pass
        
        assert cb.state == CircuitState.OPEN

    def test_thread_safety(self):
        """Test thread-safe operation."""
        cb = CircuitBreaker(failure_threshold=100)
        errors = []
        
        def make_requests(success: bool):
            try:
                for _ in range(50):
                    with cb:
                        if not success:
                            raise ValueError("Error")
            except (ValueError, CircuitBreakerOpenError):
                pass
        
        # Concurrent requests
        threads = [
            Thread(target=make_requests, args=(True,))
            for _ in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should still be closed (all successful)
        assert cb.state == CircuitState.CLOSED

    def test_reset(self):
        """Test manual reset."""
        cb = CircuitBreaker(failure_threshold=2)
        
        # Trip the breaker
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("Error")
            except ValueError:
                pass
        
        assert cb.state == CircuitState.OPEN
        
        # Reset
        cb.reset()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_metrics(self):
        """Test metrics collection."""
        cb = CircuitBreaker(failure_threshold=3)
        
        # Some successes
        for _ in range(5):
            with cb:
                pass
        
        # Some failures
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("Error")
            except ValueError:
                pass
        
        assert cb.success_count == 5
        assert cb.failure_count == 2
        assert cb.total_requests == 7
