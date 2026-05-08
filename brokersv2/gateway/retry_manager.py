"""
Retry Manager with exponential backoff and jitter.

Provides resilient retry logic for transient failures:
- Exponential backoff with configurable base/max delay
- Jitter to prevent thundering herd
- Retry on specific exception types
- Circuit breaker integration support
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Coroutine,
    List,
    Optional,
    Set,
    Type,
    Union,
)

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    
    # Retry limits
    max_retries: int = 3
    base_delay: float = 1.0  # Base delay in seconds
    max_delay: float = 60.0  # Maximum delay cap
    exponential_base: float = 2.0  # Base for exponential calculation
    
    # Jitter configuration
    jitter_enabled: bool = True
    jitter_factor: float = 0.1  # 10% jitter
    
    # Retryable exceptions
    retryable_exceptions: Set[Type[Exception]] = field(default_factory=lambda: {
        ConnectionError,
        TimeoutError,
        OSError,
    })
    
    # Logging
    log_retries: bool = True
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for given attempt number.
        
        Formula: min(base_delay * exponential_base^attempt + jitter, max_delay)
        """
        # Exponential backoff
        delay = self.base_delay * (self.exponential_base ** attempt)
        
        # Add jitter if enabled
        if self.jitter_enabled:
            jitter = delay * self.jitter_factor * random.random()
            delay += jitter
        
        # Cap at max delay
        return min(delay, self.max_delay)
    
    def should_retry(self, exception: Exception) -> bool:
        """Check if exception is retryable."""
        return isinstance(exception, tuple(self.retryable_exceptions))


class RetryManager:
    """
    Manages retry logic with exponential backoff and jitter.
    
    Usage:
        manager = RetryManager(max_retries=3, base_delay=1.0)
        
        # With async function
        result = await manager.execute_with_retry(
            async_func,
            *args,
            **kwargs
        )
        
        # With custom config
        config = RetryConfig(max_retries=5, base_delay=0.5)
        manager = RetryManager(config=config)
    """
    
    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()
        self._retry_count = 0
        self._total_retries = 0
        self._last_exception: Optional[Exception] = None
    
    async def execute_with_retry(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute async function with retry logic.
        
        Args:
            func: Async callable to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from successful function call
            
        Raises:
            Last exception if all retries exhausted
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                # Execute function
                result = await func(*args, **kwargs)
                
                # Log success after retries
                if attempt > 0 and self.config.log_retries:
                    logger.info(
                        f"Function succeeded after {attempt} retries"
                    )
                
                self._retry_count = attempt
                return result
                
            except Exception as e:
                last_exception = e
                self._last_exception = e
                
                # Check if we should retry
                if not self.config.should_retry(e):
                    logger.error(f"Non-retryable error: {e}")
                    raise
                
                # Check if we have retries left
                if attempt >= self.config.max_retries:
                    self._retry_count = self.config.max_retries
                    logger.error(
                        f"All {self.config.max_retries} retries exhausted. "
                        f"Last error: {e}"
                    )
                    raise
                
                # Calculate delay
                delay = self.config.calculate_delay(attempt)
                
                if self.config.log_retries:
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.config.max_retries + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                
                # Wait before retry
                await asyncio.sleep(delay)
                self._total_retries += 1
        
        # Should never reach here, but just in case
        if last_exception:
            raise last_exception
    
    def execute_with_retry_sync(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute sync function with retry logic.
        
        Args:
            func: Sync callable to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from successful function call
            
        Raises:
            Last exception if all retries exhausted
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                # Execute function
                result = func(*args, **kwargs)
                
                # Log success after retries
                if attempt > 0 and self.config.log_retries:
                    logger.info(
                        f"Function succeeded after {attempt} retries"
                    )
                
                self._retry_count = attempt
                return result
                
            except Exception as e:
                last_exception = e
                self._last_exception = e
                
                # Check if we should retry
                if not self.config.should_retry(e):
                    logger.error(f"Non-retryable error: {e}")
                    raise
                
                # Check if we have retries left
                if attempt >= self.config.max_retries:
                    self._retry_count = self.config.max_retries
                    logger.error(
                        f"All {self.config.max_retries} retries exhausted. "
                        f"Last error: {e}"
                    )
                    raise
                
                # Calculate delay
                delay = self.config.calculate_delay(attempt)
                
                if self.config.log_retries:
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.config.max_retries + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                
                # Wait before retry (sync version)
                time.sleep(delay)
                self._total_retries += 1
        
        # Should never reach here, but just in case
        if last_exception:
            raise last_exception
    
    @property
    def retry_count(self) -> int:
        """Number of retries in last execution."""
        return self._retry_count
    
    @property
    def total_retries(self) -> int:
        """Total retries across all executions."""
        return self._total_retries
    
    @property
    def last_exception(self) -> Optional[Exception]:
        """Last exception encountered."""
        return self._last_exception
    
    def reset_stats(self) -> None:
        """Reset retry statistics."""
        self._retry_count = 0
        self._total_retries = 0
        self._last_exception = None
