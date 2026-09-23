"""
Dhan Resilience Patterns - Implementation of rate limiting and circuit breaker.

This module provides resilience pattern implementations for robust API
communication with the Dhan API.

Features:
    - Token bucket rate limiting
    - Circuit breaker with state machine
    - Multiple rate limit categories
    - Automatic recovery

Example:
    >>> from brokers.broker.dhan.infrastructure import (
    ...     TokenBucketRateLimiter,
    ...     DhanCircuitBreaker,
    ... )
    >>> 
    >>> # Rate limiting
    >>> rate_limiter = TokenBucketRateLimiter()
    >>> await rate_limiter.acquire('market_data')
    >>> 
    >>> # Circuit breaker
    >>> circuit_breaker = DhanCircuitBreaker()
    >>> result = await circuit_breaker.execute(lambda: risky_operation())
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, Callable, TypeVar, Awaitable

from brokers.broker.dhan.ports import (
    IRateLimiter,
)
from shared.resilience import (
    CircuitBreaker as SharedCircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)
from brokers.broker.logging import get_logger
from brokers.broker.dhan.domain import (
    DhanNetworkError,
    RATE_LIMIT_MARKET_DATA,
    RATE_LIMIT_HISTORICAL,
    RATE_LIMIT_ORDERS,
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_OPTION_CHAIN,
    RATE_BURST_MARKET_DATA,
    RATE_BURST_HISTORICAL,
    RATE_BURST_ORDERS,
    RATE_BURST_DEFAULT,
    RATE_BURST_OPTION_CHAIN,
)


# =============================================================================
# Logger
# =============================================================================

logger = get_logger("dhan.resilience")


# =============================================================================
# Type Variables
# =============================================================================

T = TypeVar('T')


# =============================================================================
# Rate Limit Configuration
# =============================================================================

@dataclass
class RateLimitConfig:
    """
    Configuration for a rate limit category.
    
    Attributes:
        rate: Requests per second allowed.
        burst: Maximum burst capacity.
    """
    rate: float  # Requests per second
    burst: int   # Maximum burst capacity


# Default rate limit configurations by category
DEFAULT_RATE_LIMITS: Dict[str, RateLimitConfig] = {
    "default": RateLimitConfig(rate=RATE_LIMIT_DEFAULT, burst=RATE_BURST_DEFAULT),
    "market_data": RateLimitConfig(rate=RATE_LIMIT_MARKET_DATA, burst=RATE_BURST_MARKET_DATA),
    "historical": RateLimitConfig(rate=RATE_LIMIT_HISTORICAL, burst=RATE_BURST_HISTORICAL),
    "orders": RateLimitConfig(rate=RATE_LIMIT_ORDERS, burst=RATE_BURST_ORDERS),
    # Dhan docs: 1 unique request per 3 seconds for /optionchain endpoints
    "option_chain": RateLimitConfig(rate=RATE_LIMIT_OPTION_CHAIN, burst=RATE_BURST_OPTION_CHAIN),
}


# =============================================================================
# Token Bucket Rate Limiter
# =============================================================================

class TokenBucketRateLimiter(IRateLimiter):
    """
    Token bucket rate limiter implementation.
    
    Implements the IRateLimiter protocol using the token bucket algorithm.
    Supports multiple rate limit categories with configurable rates and burst limits.
    
    The token bucket algorithm allows for burst traffic up to the bucket capacity
    while maintaining the average rate limit over time.
    
    Attributes:
        configs: Rate limit configurations by category.
    
    Example:
        >>> rate_limiter = TokenBucketRateLimiter()
        >>> 
        >>> # Acquire token for market data
        >>> await rate_limiter.acquire('market_data')
        >>> 
        >>> # Now safe to make market data API call
        >>> response = await http_client.get("/market-data")
    """
    
    def __init__(
        self,
        configs: Optional[Dict[str, RateLimitConfig]] = None,
    ) -> None:
        """
        Initialize the rate limiter.
        
        Args:
            configs: Optional custom rate limit configurations.
                If not provided, defaults are used.
        """
        self._configs = configs or DEFAULT_RATE_LIMITS
        
        # Token buckets: category -> (tokens, last_update_time)
        self._buckets: Dict[str, tuple] = {}
        
        # Locks created lazily in the running loop to avoid event-loop binding issues
        self._locks: Dict[str, asyncio.Lock] = {}

        # Initialize buckets
        for category, config in self._configs.items():
            self._buckets[category] = (float(config.burst), time.monotonic())
        
        logger.debug(
            f"TokenBucketRateLimiter initialized with {len(self._configs)} categories"
        )
    
    async def acquire(self, category: str = 'default') -> None:
        """
        Acquire a rate limit token, waiting if necessary.
        
        Blocks until a token is available in the specified category.
        
        Args:
            category: Rate limit category:
                - 'default': General API calls
                - 'market_data': Market data endpoints
                - 'historical': Historical data endpoints
                - 'orders': Order placement endpoints
        
        Raises:
            DhanRateLimitError: If rate limit exceeded and no wait allowed.
        """
        # Get or create bucket for category
        if category not in self._buckets:
            # Use default config for unknown categories
            default_config = self._configs.get("default", DEFAULT_RATE_LIMITS["default"])
            self._configs[category] = default_config
            self._buckets[category] = (float(default_config.burst), time.monotonic())

        # Lazily create lock bound to the running event loop
        if category not in self._locks:
            self._locks[category] = asyncio.Lock()

        lock = self._locks[category]
        config = self._configs[category]
        
        async with lock:
            # Refill tokens based on elapsed time
            tokens, last_update = self._buckets[category]
            now = time.monotonic()
            elapsed = now - last_update
            
            # Add tokens based on rate
            new_tokens = elapsed * config.rate
            tokens = min(float(config.burst), tokens + new_tokens)
            
            # Check if we have a token
            if tokens >= 1.0:
                # Consume a token
                tokens -= 1.0
                self._buckets[category] = (tokens, now)
                logger.debug(f"Rate limit token acquired for {category}: {tokens:.2f} remaining")
                return
            
            # Calculate wait time
            wait_time = (1.0 - tokens) / config.rate
            
            logger.debug(
                f"Rate limit wait required for {category}: {wait_time:.3f}s"
            )
            
            # Wait for token to be available
            await asyncio.sleep(wait_time)
            
            # Update bucket after wait
            self._buckets[category] = (0.0, time.monotonic())
    
    def get_tokens(self, category: str = 'default') -> float:
        """
        Get current token count for a category.
        
        Args:
            category: Rate limit category.
        
        Returns:
            Current number of tokens available.
        """
        if category not in self._buckets:
            return 0.0
        
        tokens, last_update = self._buckets[category]
        config = self._configs.get(category, DEFAULT_RATE_LIMITS["default"])
        
        # Calculate current tokens (without consuming)
        now = time.monotonic()
        elapsed = now - last_update
        new_tokens = elapsed * config.rate
        
        return min(float(config.burst), tokens + new_tokens)
    
    def get_wait_time(self, category: str = 'default') -> float:
        """
        Get estimated wait time for a token.
        
        Args:
            category: Rate limit category.
        
        Returns:
            Estimated wait time in seconds (0 if tokens available).
        """
        tokens = self.get_tokens(category)
        if tokens >= 1.0:
            return 0.0
        
        config = self._configs.get(category, DEFAULT_RATE_LIMITS["default"])
        return (1.0 - tokens) / config.rate
    
    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"TokenBucketRateLimiter(categories={list(self._configs.keys())})"
        )


# =============================================================================
# Dhan Circuit Breaker (extends unified CircuitBreaker)
# =============================================================================

class DhanCircuitBreaker(SharedCircuitBreaker):
    """
    Dhan-specific circuit breaker implementation.

    .. deprecated::
        This class is **deprecated** and exists only for backward compatibility.
        New code should use ``CircuitBreaker`` from ``brokers.broker.ports``
        directly. The only Dhan-specific behaviour this subclass adds is
        re-raising ``CircuitBreakerError`` as ``DhanNetworkError`` in
        ``execute()``, plus a ``force_open()`` helper. Both can be handled at
        the call-site instead.

    Migration path::

        # Old (deprecated)
        from brokers.broker.dhan.infrastructure.resilience import DhanCircuitBreaker
        cb = DhanCircuitBreaker()

        # New (preferred)
        from brokers.broker.ports import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

    Example:
        >>> circuit_breaker = DhanCircuitBreaker()
        >>>
        >>> # Execute operation through circuit breaker
        >>> try:
        ...     result = await circuit_breaker.execute(
        ...         lambda: http_client.get("/orders")
        ...     )
        ... except DhanNetworkError as e:
        ...     print(f"Circuit breaker blocked or operation failed: {e}")
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 3
    ) -> None:
        """
        Initialize the circuit breaker.
        """
        super().__init__(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
        )
        
        # Expose a _config-like proxy so tests can mutate thresholds
        self._config = self

        logger.debug(
            f"DhanCircuitBreaker initialized with "
            f"failure_threshold={self.failure_threshold}, "
            f"timeout={self.recovery_timeout}s"
        )

    @property
    def timeout(self):
        return self.recovery_timeout

    @timeout.setter
    def timeout(self, value):
        self.recovery_timeout = value

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]]
    ) -> T:
        try:
            return await super().execute(operation)
        except CircuitBreakerError as e:
            raise DhanNetworkError(str(e)) from e
    
    def reset(self) -> None:
        """
        Reset the circuit breaker to closed state.
        
        Useful for manual intervention or testing.
        """
        super().reset()
        logger.info("DhanCircuitBreaker reset to CLOSED state")
    
    def force_open(self) -> None:
        """
        Force the circuit breaker to open state.
        
        Useful for maintenance or manual intervention.
        """
        self._state = CircuitState.OPEN
        logger.warning("DhanCircuitBreaker forced to OPEN state")
    
    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"DhanCircuitBreaker(state={self._state.value}, "
            f"failures={self._failure_count}, "
            f"successes={self._success_count})"
        )