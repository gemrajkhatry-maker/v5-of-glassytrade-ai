"""Tests for RetryManager - Exponential backoff with jitter."""

import asyncio
import time
import pytest
from brokersv2.infrastructure.retry_manager import (
    RetryManager,
    RetryPolicy,
    RetryExhaustedError,
    RetryMetrics,
)


@pytest.mark.asyncio
async def test_successful_first_attempt():
    """Operation succeeds immediately without retries."""
    
    async def successful_operation():
        return "success"
    
    manager = RetryManager()
    policy = RetryPolicy(max_retries=3, base_delay=0.1)
    
    result = await manager.execute_with_retry(successful_operation, policy=policy)
    
    assert result == "success"
    assert policy.metrics.total_attempts == 1
    assert policy.metrics.successful_attempts == 1
    assert policy.metrics.failed_attempts == 0


@pytest.mark.asyncio
async def test_retry_on_connection_error():
    """Retries on ConnectionError and eventually succeeds."""
    
    attempt_count = 0
    
    async def flaky_operation():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ConnectionError(f"Connection failed (attempt {attempt_count})")
        return "success after retries"
    
    manager = RetryManager()
    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    
    result = await manager.execute_with_retry(flaky_operation, policy=policy)
    
    assert result == "success after retries"
    assert attempt_count == 3
    assert policy.metrics.total_attempts == 3
    assert policy.metrics.successful_attempts == 1
    assert policy.metrics.failed_attempts == 2
    assert policy.metrics.total_retries == 2


@pytest.mark.asyncio
async def test_max_retries_exceeded():
    """Raises RetryExhaustedError after max retries."""
    
    async def always_failing():
        raise ConnectionError("Persistent connection failure")
    
    manager = RetryManager()
    policy = RetryPolicy(max_retries=2, base_delay=0.01)
    
    with pytest.raises(RetryExhaustedError) as exc_info:
        await manager.execute_with_retry(always_failing, policy=policy)
    
    assert "Max retries (2) exceeded" in str(exc_info.value)
    assert isinstance(exc_info.value.last_exception, ConnectionError)
    assert policy.metrics.total_attempts == 3
    assert policy.metrics.failed_attempts == 3


@pytest.mark.asyncio
async def test_exponential_backoff_timing():
    """Delays increase exponentially (base_delay * exponential_base^attempt)."""
    
    attempt_count = 0
    
    async def failing_operation():
        nonlocal attempt_count
        attempt_count += 1
        raise ConnectionError("Connection timeout")
    
    manager = RetryManager()
    policy = RetryPolicy(
        max_retries=2,
        base_delay=0.1,
        exponential_base=2.0,
        jitter=False  # Disable for predictable timing
    )
    
    start_time = time.monotonic()
    
    with pytest.raises(RetryExhaustedError):
        await manager.execute_with_retry(failing_operation, policy=policy)
    
    elapsed = time.monotonic() - start_time
    
    # Expected delays: 0.1s (attempt 1) + 0.2s (attempt 2) = 0.3s total
    # Allow 50% tolerance for system scheduling
    assert elapsed >= 0.15, f"Expected at least 0.15s, got {elapsed:.2f}s"
    assert attempt_count == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_no_retry_on_non_retryable_exception():
    """ValueError raises immediately without retry."""
    
    attempt_count = 0
    
    async def invalid_operation():
        nonlocal attempt_count
        attempt_count += 1
        raise ValueError("Invalid argument")
    
    manager = RetryManager()
    policy = RetryPolicy(max_retries=3, base_delay=0.1)
    
    with pytest.raises(ValueError, match="Invalid argument"):
        await manager.execute_with_retry(invalid_operation, policy=policy)
    
    assert attempt_count == 1
    assert policy.metrics.total_attempts == 1
    assert policy.metrics.failed_attempts == 1
