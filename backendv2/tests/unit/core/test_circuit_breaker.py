"""Tests for CircuitBreaker — adaptive circuit breaker for trading risk.

Behavior: CircuitBreaker opens after failures, transitions to half-open
after timeout, and closes after successes.
"""
from __future__ import annotations

import time
import pytest

from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState


class TestCircuitBreaker:
    """Tests for CircuitBreaker behavior through public interface."""

    def test_starts_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker()
        
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open

    def test_opens_after_failure_threshold(self):
        """Circuit should open after N consecutive failures."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open  # Not yet at threshold
        
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_open

    def test_resets_to_half_open_after_timeout(self):
        """Circuit should transition to HALF_OPEN after timeout."""
        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.1
        ))
        
        cb.record_failure()
        assert cb.is_open
        
        time.sleep(0.2)  # Wait for timeout
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_after_success_threshold_in_half_open(self):
        """Circuit should close after N successes in HALF_OPEN state."""
        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.1,
            success_threshold=2
        ))
        
        # Open the circuit
        cb.record_failure()
        assert cb.is_open
        
        # Wait for timeout
        time.sleep(0.2)
        assert cb.state == CircuitState.HALF_OPEN
        
        # Record successes
        cb.record_success()
        cb.record_success()
        
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open

    def test_failure_count_resets_on_success(self):
        """Success should reset failure count."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Reset
        
        # Need 3 more failures to open
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open
        
        cb.record_failure()
        assert cb.is_open

    @pytest.mark.asyncio
    async def test_decorator_blocks_when_open(self):
        """Decorator should raise RuntimeError when circuit is open."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        
        call_count = 0
        
        @cb
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")
        
        # First call fails and opens circuit
        with pytest.raises(ValueError):
            await failing_func()
        
        assert call_count == 1
        
        # Second call should be blocked by open circuit
        with pytest.raises(RuntimeError, match="OPEN"):
            await failing_func()
        
        # Function should not have been called
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_decorator_allows_when_closed(self):
        """Decorator should allow calls when circuit is closed."""
        cb = CircuitBreaker()
        
        @cb
        async def success_func():
            return 42
        
        result = await success_func()
        assert result == 42
        assert not cb.is_open

    def test_success_in_half_open_does_not_close_immediately(self):
        """Single success in HALF_OPEN should not close circuit."""
        cb = CircuitBreaker(CircuitBreakerConfig(
            failure_threshold=1,
            timeout_seconds=0.1,
            success_threshold=3
        ))
        
        cb.record_failure()
        time.sleep(0.2)
        assert cb.state == CircuitState.HALF_OPEN
        
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN  # Still half-open
        
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED  # Now closed

    def test_config_defaults(self):
        """Default config should have reasonable values."""
        config = CircuitBreakerConfig()
        
        assert config.failure_threshold == 5
        assert config.timeout_seconds == 300.0  # 5 minutes
        assert config.success_threshold == 3
