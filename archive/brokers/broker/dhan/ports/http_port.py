"""
HTTP Port - Protocol for HTTP client implementations.

This module defines the interface for HTTP clients used to communicate
with the Dhan API. Implementations can use any HTTP library (aiohttp, httpx, etc.).

Example:
    >>> from brokers.broker.dhan.ports import IHttpClient, HttpRequest
    >>> 
    >>> # Create a request
    >>> request = HttpRequest(
    ...     method="GET",
    ...     endpoint="/orders",
    ...     params={"status": "open"},
    ... )
    >>> 
    >>> # Execute the request
    >>> response = await client.request(request)
"""

from typing import Protocol, runtime_checkable, Dict, Any, Optional
from dataclasses import dataclass


# =============================================================================
# Request/Response Data Classes
# =============================================================================

@dataclass(frozen=True)
class HttpRequest:
    """Immutable HTTP request container.
    
    Attributes:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        endpoint: API endpoint path (e.g., "/orders")
        params: Optional query parameters
        json: Optional JSON body for POST/PUT requests
        headers: Optional additional headers
    
    Example:
        >>> request = HttpRequest(
        ...     method="POST",
        ...     endpoint="/orders",
        ...     json={"symbol": "NIFTY", "quantity": 50},
        ... )
    """
    method: str
    endpoint: str
    params: Optional[Dict[str, Any]] = None
    json: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class HttpResponse:
    """Immutable HTTP response container.
    
    Attributes:
        status_code: HTTP status code (200, 400, 500, etc.)
        data: Response body parsed as dictionary
        headers: Response headers
    
    Example:
        >>> response = HttpResponse(
        ...     status_code=200,
        ...     data={"orderId": "12345"},
        ...     headers={"content-type": "application/json"},
        ... )
    """
    status_code: int
    data: Dict[str, Any]
    headers: Dict[str, str]


# =============================================================================
# HTTP Client Protocol
# =============================================================================

@runtime_checkable
class IHttpClient(Protocol):
    """Protocol for HTTP client implementations.
    
    This protocol defines the interface for making HTTP requests to the Dhan API.
    Implementations should handle:
        - Authentication headers injection
        - Request/response logging
        - Error handling and retries
        - Connection pooling
    
    All methods are async to support non-blocking I/O.
    
    Example:
        >>> class DhanHttpClient:
        ...     async def get(self, endpoint: str, params: Optional[Dict] = None) -> HttpResponse:
        ...         # Implementation using aiohttp/httpx
        ...         pass
    """
    
    async def get(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> HttpResponse:
        """Execute a GET request.
        
        Args:
            endpoint: API endpoint path (e.g., "/orders")
            params: Optional query parameters
        
        Returns:
            HttpResponse with status code, data, and headers
        
        Raises:
            DhanNetworkError: If network error occurs
            DhanTimeoutError: If request times out
            DhanRateLimitError: If rate limit exceeded
        """
        ...
    
    async def post(
        self, 
        endpoint: str, 
        json: Optional[Dict[str, Any]] = None
    ) -> HttpResponse:
        """Execute a POST request.
        
        Args:
            endpoint: API endpoint path (e.g., "/orders")
            json: Optional JSON body
        
        Returns:
            HttpResponse with status code, data, and headers
        
        Raises:
            DhanNetworkError: If network error occurs
            DhanTimeoutError: If request times out
            DhanRateLimitError: If rate limit exceeded
        """
        ...
    
    async def request(self, request: HttpRequest) -> HttpResponse:
        """Execute a generic HTTP request.
        
        This method provides full control over the request including
        method, headers, and body.
        
        Args:
            request: HttpRequest with method, endpoint, params, json, headers
        
        Returns:
            HttpResponse with status code, data, and headers
        
        Raises:
            DhanNetworkError: If network error occurs
            DhanTimeoutError: If request times out
            DhanRateLimitError: If rate limit exceeded
        """
        ...
    
    async def close(self) -> None:
        """Close the HTTP client and release resources.
        
        Should be called when the client is no longer needed.
        Implementations should close connection pools and cleanup.
        """
        ...
