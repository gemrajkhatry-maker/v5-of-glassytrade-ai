"""
Request Dispatcher with retry and circuit breaker integration.

Centralized request handling for broker API calls:
- Automatic retry on transient failures
- Circuit breaker protection
- Request logging and metrics
- Timeout management
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

from brokersv2.core.resilience import CircuitBreaker
from brokersv2.gateway.retry_manager import RetryManager, RetryConfig

logger = logging.getLogger(__name__)


class RequestPriority(Enum):
    """Request priority levels."""
    LOW = "low"  # Market data, historical data
    NORMAL = "normal"  # Account info, positions
    HIGH = "high"  # Order placement, modification
    CRITICAL = "critical"  # Order cancellation, emergency close


@dataclass
class RequestContext:
    """Context for a request."""
    
    method: str  # HTTP method or operation name
    endpoint: str  # API endpoint
    priority: RequestPriority = RequestPriority.NORMAL
    timeout: float = 30.0  # Request timeout in seconds
    idempotency_key: Optional[str] = None  # For idempotent operations
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def key(self) -> str:
        """Unique key for this request."""
        return f"{self.method}:{self.endpoint}"


@dataclass
class RequestMetrics:
    """Metrics for request dispatcher."""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    retried_requests: int = 0
    circuit_broken_requests: int = 0
    total_latency: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Success rate percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def average_latency(self) -> float:
        """Average request latency in seconds."""
        if self.total_requests == 0:
            return 0.0
        return self.total_latency / self.total_requests
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "retried_requests": self.retried_requests,
            "circuit_broken_requests": self.circuit_broken_requests,
            "success_rate": round(self.success_rate, 2),
            "average_latency": round(self.average_latency, 3),
        }


class RequestDispatcher:
    """
    Centralized request dispatcher with retry and circuit breaker.
    
    Usage:
        dispatcher = RequestDispatcher(
            retry_manager=retry_manager,
            circuit_breaker=circuit_breaker
        )
        
        # Execute request
        result = await dispatcher.execute(
            request_context=RequestContext(method="GET", endpoint="/quotes"),
            func=fetch_quotes,
            symbol="RELIANCE"
        )
    """
    
    def __init__(
        self,
        retry_manager: Optional[RetryManager] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        default_timeout: float = 30.0,
    ):
        self.retry_manager = retry_manager or RetryManager()
        self.circuit_breaker = circuit_breaker
        self.default_timeout = default_timeout
        self.metrics = RequestMetrics()
        self._request_log: list = []
    
    async def execute(
        self,
        request_context: RequestContext,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute request with retry and circuit breaker protection.
        
        Args:
            request_context: Request metadata
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from function call
            
        Raises:
            Exception from function call (after retries exhausted)
        """
        start_time = time.time()
        self.metrics.total_requests += 1
        
        # Log request
        logger.debug(
            f"Dispatching {request_context.method} {request_context.endpoint} "
            f"[priority={request_context.priority.value}]"
        )
        
        try:
            # Check circuit breaker
            if self.circuit_breaker and self.circuit_breaker.state.value == "open":
                self.metrics.circuit_broken_requests += 1
                logger.warning(
                    f"Circuit breaker open, rejecting request: {request_context.key}"
                )
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open for {request_context.key}"
                )
            
            # Add timeout to kwargs if not present
            if 'timeout' not in kwargs:
                kwargs['timeout'] = request_context.timeout
            
            # Execute with retry
            result = await self.retry_manager.execute_with_retry(
                func,
                *args,
                **kwargs
            )
            
            # Record success
            elapsed = time.time() - start_time
            self.metrics.successful_requests += 1
            self.metrics.total_latency += elapsed
            
            # Record retry count
            if self.retry_manager.retry_count > 0:
                self.metrics.retried_requests += 1
            
            # Log success
            logger.debug(
                f"Request succeeded: {request_context.key} "
                f"latency={elapsed:.3f}s "
                f"retries={self.retry_manager.retry_count}"
            )
            
            return result
            
        except CircuitBreakerOpenError:
            raise
        except Exception as e:
            # Record failure
            elapsed = time.time() - start_time
            self.metrics.failed_requests += 1
            self.metrics.total_latency += elapsed
            
            logger.error(
                f"Request failed: {request_context.key} "
                f"error={e} "
                f"latency={elapsed:.3f}s"
            )
            raise
    
    def execute_sync(
        self,
        request_context: RequestContext,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute sync request with retry protection.
        
        Args:
            request_context: Request metadata
            func: Sync function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from function call
        """
        start_time = time.time()
        self.metrics.total_requests += 1
        
        try:
            # Execute with retry (sync version)
            result = self.retry_manager.execute_with_retry_sync(
                func,
                *args,
                **kwargs
            )
            
            # Record success
            elapsed = time.time() - start_time
            self.metrics.successful_requests += 1
            self.metrics.total_latency += elapsed
            
            if self.retry_manager.retry_count > 0:
                self.metrics.retried_requests += 1
            
            return result
            
        except Exception as e:
            # Record failure
            elapsed = time.time() - start_time
            self.metrics.failed_requests += 1
            self.metrics.total_latency += elapsed
            
            logger.error(
                f"Sync request failed: {request_context.key} "
                f"error={e}"
            )
            raise
    
    def log_request(self, context: RequestContext, success: bool, latency: float) -> None:
        """Log request for audit trail."""
        log_entry = {
            "timestamp": time.time(),
            "method": context.method,
            "endpoint": context.endpoint,
            "priority": context.priority.value,
            "success": success,
            "latency": latency,
            "idempotency_key": context.idempotency_key,
        }
        self._request_log.append(log_entry)
        
        # Keep only last 1000 entries
        if len(self._request_log) > 1000:
            self._request_log = self._request_log[-1000:]
    
    def get_recent_requests(self, limit: int = 50) -> list:
        """Get recent request log entries."""
        return self._request_log[-limit:]
    
    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self.metrics = RequestMetrics()
    
    def get_status(self) -> Dict[str, Any]:
        """Get dispatcher status."""
        return {
            "metrics": self.metrics.to_dict(),
            "circuit_breaker": (
                self.circuit_breaker.state.value
                if self.circuit_breaker
                else "not_configured"
            ),
            "recent_requests": len(self._request_log),
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request is rejected."""
    pass
