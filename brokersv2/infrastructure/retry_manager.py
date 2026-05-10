"""Retry Manager - Exponential backoff with jitter and circuit breaker integration."""

import asyncio
import random
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple, Type

logger = logging.getLogger(__name__)


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""
    
    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        super().__init__(message)
        self.last_exception = last_exception


@dataclass
class RetryMetrics:
    """Track retry statistics."""
    total_attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    total_retries: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.successful_attempts / self.total_attempts
    
    @property
    def retry_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.total_retries / self.total_attempts


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.25  # ±25%
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )
    circuit_breaker: Optional[Any] = None
    metrics: Optional[RetryMetrics] = field(default_factory=RetryMetrics)


class RetryManager:
    """
    Manages retry logic with exponential backoff and jitter.
    
    Features:
    - Exponential backoff with configurable base
    - Random jitter to prevent thundering herd
    - Circuit breaker integration
    - Comprehensive metrics tracking
    - Configurable retryable exceptions
    
    Usage:
        retry_mgr = RetryManager()
        policy = RetryPolicy(max_retries=3, base_delay=1.0)
        
        result = await retry_mgr.execute_with_retry(
            coro=api_call(),
            policy=policy
        )
    """
    
    def __init__(self, default_policy: Optional[RetryPolicy] = None):
        self.default_policy = default_policy or RetryPolicy()
    
    async def execute_with_retry(
        self,
        operation: Any,
        policy: Optional[RetryPolicy] = None,
    ) -> Any:
        """
        Execute operation with retry logic.
        
        Args:
            operation: Coroutine function or callable to execute
            policy: Retry policy (uses default if None)
            
        Returns:
            Result from successful execution
            
        Raises:
            RetryExhaustedError: If all retries exhausted
        """
        policy = policy or self.default_policy
        last_exception: Optional[Exception] = None
        
        for attempt in range(policy.max_retries + 1):
            policy.metrics.total_attempts += 1
            
            try:
                # Check circuit breaker
                if policy.circuit_breaker and not policy.circuit_breaker.allow_request():
                    logger.warning("Circuit breaker open, skipping retry")
                    raise RetryExhaustedError(
                        "Circuit breaker open",
                        last_exception=last_exception
                    )
                
                # Execute - create fresh coroutine each attempt
                if callable(operation):
                    result = operation()
                    if asyncio.iscoroutine(result):
                        result = await result
                elif asyncio.iscoroutine(operation):
                    # Coroutine already created (not recommended for retries)
                    result = await operation
                else:
                    result = operation
                
                # Success
                policy.metrics.successful_attempts += 1
                if attempt > 0:
                    policy.metrics.total_retries += attempt  # Count all retries
                
                if policy.circuit_breaker:
                    policy.circuit_breaker.record_success()
                
                logger.debug(f"Operation succeeded on attempt {attempt + 1}")
                return result
                
            except Exception as e:
                last_exception = e
                policy.metrics.failed_attempts += 1
                
                # Check if retryable
                if not isinstance(e, policy.retryable_exceptions):
                    logger.warning(f"Non-retryable exception: {type(e).__name__}: {e}")
                    raise
                
                # Check retries left
                if attempt >= policy.max_retries:
                    logger.error(
                        f"All {policy.max_retries + 1} attempts exhausted. "
                        f"Last error: {type(e).__name__}: {e}"
                    )
                    if policy.circuit_breaker:
                        policy.circuit_breaker.record_failure()
                    raise RetryExhaustedError(
                        f"Max retries ({policy.max_retries}) exceeded",
                        last_exception=e
                    )
                
                # Calculate delay
                delay = self._calculate_delay(attempt, policy)
                logger.warning(
                    f"Attempt {attempt + 1} failed: {type(e).__name__}: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                
                await asyncio.sleep(delay)
        
        raise RetryExhaustedError(
            "Unexpected retry exhaustion",
            last_exception=last_exception
        )
    
    def _calculate_delay(self, attempt: int, policy: RetryPolicy) -> float:
        """Calculate delay with exponential backoff and jitter."""
        delay = policy.base_delay * (policy.exponential_base ** attempt)
        delay = min(delay, policy.max_delay)
        
        if policy.jitter:
            jitter_range = delay * policy.jitter_factor
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0.0, delay)
    
    def get_metrics(self) -> RetryMetrics:
        """Get current retry metrics."""
        return self.default_policy.metrics
