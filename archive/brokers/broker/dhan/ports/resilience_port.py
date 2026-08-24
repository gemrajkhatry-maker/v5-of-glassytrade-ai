"""
Resilience Port - Protocol for resilience patterns.

This module defines interfaces for rate limiting and circuit breaker patterns
to ensure robust API communication.

Example:
    >>> from brokers.broker.dhan.ports import IRateLimiter, ICircuitBreaker
    >>> 
    >>> # Rate limiting
    >>> await rate_limiter.acquire('market_data')
    >>> 
    >>> # Circuit breaker
    >>> result = await circuit_breaker.execute(lambda: risky_operation())
"""

from typing import Protocol, runtime_checkable, Callable, TypeVar


# =============================================================================
# Generic Type Variable
# =============================================================================

T = TypeVar('T')


# =============================================================================
# Rate Limiter Protocol
# =============================================================================

@runtime_checkable
class IRateLimiter(Protocol):
    """Protocol for rate limiting.
    
    This protocol defines the interface for rate limiting API calls.
    Implementations should handle:
        - Multiple rate limit categories (market_data, orders, historical)
        - Token bucket or sliding window algorithms
        - Burst rate limiting
    
    All methods are async to support waiting for rate limit tokens.
    
    Example:
        >>> class TokenBucketRateLimiter:
        ...     async def acquire(self, category: str = 'default') -> None:
        ...         # Wait for a token in the specified category
        ...         pass
    """
    
    async def acquire(self, category: str = 'default') -> None:
        """Acquire a rate limit token, waiting if necessary.
        
        Blocks until a token is available in the specified category.
        
        Args:
            category: Rate limit category:
                - 'default': General API calls
                - 'market_data': Market data endpoints
                - 'historical': Historical data endpoints
                - 'orders': Order placement endpoints
        
        Raises:
            DhanRateLimitError: If rate limit exceeded and no wait allowed
        
        Example:
            >>> await rate_limiter.acquire('market_data')
            >>> # Now safe to make market data API call
        """
        ...


# =============================================================================
# Circuit Breaker Protocol
# =============================================================================

@runtime_checkable
class ICircuitBreaker(Protocol):
    """Protocol for circuit breaker pattern.
    
    This protocol defines the interface for the circuit breaker pattern
    to prevent cascading failures. Implementations should handle:
        - State transitions (closed -> open -> half_open -> closed)
        - Failure counting and threshold detection
        - Automatic recovery attempts
    
    States:
        - 'closed': Normal operation, requests pass through
        - 'open': Circuit tripped, requests fail fast
        - 'half_open': Testing if service recovered
    
    Example:
        >>> class DhanCircuitBreaker:
        ...     async def execute(self, operation: Callable[[], T]) -> T:
        ...         if self.state == 'open':
        ...             raise DhanNetworkError("Circuit breaker open")
        ...         # Execute operation with failure tracking
        ...         pass
    """
    
    async def execute(self, operation: Callable[[], T]) -> T:
        """Execute an operation through the circuit breaker.
        
        If the circuit is closed, executes the operation.
        If the circuit is open, fails fast without calling the operation.
        If the circuit is half-open, allows one test request.
        
        Args:
            operation: Async callable to execute
        
        Returns:
            Result of the operation
        
        Raises:
            DhanNetworkError: If circuit is open
            Exception: Any exception from the operation
        
        Example:
            >>> result = await circuit_breaker.execute(
            ...     lambda: http_client.get("/orders")
            ... )
        """
        ...
    
    @property
    def state(self) -> str:
        """Get the current circuit breaker state.
        
        Returns:
            One of: 'closed', 'open', 'half_open'
        """
        ...
