"""
Dhan HTTP Client - Implementation of IHttpClient protocol.

This module provides the HTTP client implementation for communicating
with the Dhan API using aiohttp.

Features:
    - Async HTTP requests with aiohttp
    - Retry logic with exponential backoff
    - Timeout handling
    - Proper error mapping to domain errors
    - Connection pooling
    - Auto token refresh on 401 errors

Example:
    >>> from brokers.broker.dhan.infrastructure import DhanHttpClient
    >>> 
    >>> async with DhanHttpClient(
    ...     base_url="https://api.dhan.co",
    ...     access_token="your_token",
    ... ) as client:
    ...     response = await client.get("/orders")
    ...     print(response.data)
"""

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, TYPE_CHECKING

import aiohttp

from brokers.broker.logging import get_logger, get_correlation_id
from brokers.broker.dhan.ports import (
    IHttpClient,
    HttpRequest,
    HttpResponse,
)
from brokers.broker.dhan.domain import (
    DhanError,
    DhanNetworkError,
    DhanConnectionError,
    DhanTimeoutError,
    DhanRateLimitError,
    DhanAuthError,
    DhanTokenExpiredError,
    DhanTokenInvalidError,
    DhanInvalidDataError,
    create_error_from_response,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    ERROR_CODE_RATE_LIMIT,
    ERROR_CODE_TIMEOUT,
    ERROR_CODE_CONNECTION_ERROR,
    ERROR_CODE_INVALID_TOKEN,
    ERROR_CODE_TOKEN_EXPIRED,
)

if TYPE_CHECKING:
    from brokers.broker.dhan.infrastructure.auth_provider import DhanAuthProvider


# =============================================================================
# Logger
# =============================================================================

logger = get_logger("dhan.http")


# =============================================================================
# Retry Configuration
# =============================================================================

@dataclass
class RetryConfig:
    """
    Configuration for HTTP request retry behavior.
    
    Attributes:
        max_retries: Maximum number of retry attempts.
        backoff_factor: Multiplier for exponential backoff (seconds).
        max_delay: Maximum delay between retries (seconds).
        retry_on_status: HTTP status codes that trigger retry.
    
    Example:
        >>> config = RetryConfig(
        ...     max_retries=3,
        ...     backoff_factor=0.5,
        ...     max_delay=30.0,
        ... )
    """
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_factor: float = DEFAULT_RETRY_BACKOFF_FACTOR
    max_delay: float = DEFAULT_RETRY_MAX_DELAY_SECONDS
    retry_on_status: tuple = (408, 429, 500, 502, 503, 504)
    
    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given retry attempt.
        
        Uses exponential backoff with jitter.
        
        Args:
            attempt: The retry attempt number (0-indexed).
        
        Returns:
            Delay in seconds before the next retry.
        """
        # Exponential backoff: backoff_factor * 2^attempt
        delay = self.backoff_factor * (2 ** attempt)
        # Cap at max delay
        return min(delay, self.max_delay)


# =============================================================================
# Dhan HTTP Client Implementation
# =============================================================================

class DhanHttpClient(IHttpClient):
    """
    HTTP client implementation for the Dhan API.
    
    Implements the IHttpClient protocol using aiohttp for async HTTP requests.
    Handles authentication, retries, timeouts, and error mapping.
    
    Features:
        - Auto token refresh on 401 errors (when auth_provider is set)
        - Proactive token refresh before expiry
        - Retry logic with exponential backoff
        - Connection pooling
    
    Attributes:
        base_url: Base URL for the Dhan API.
        access_token: Access token for authentication.
        timeout: Request timeout in seconds.
        retry_config: Retry configuration.
        auth_provider: Optional auth provider for auto token refresh.
    
    Example:
        >>> client = DhanHttpClient(
        ...     base_url="https://api.dhan.co",
        ...     access_token="your_token",
        ... )
        >>> 
        >>> # Use as context manager for automatic cleanup
        >>> async with client:
        ...     response = await client.get("/orders")
        ...     print(response.data)
        >>> 
        >>> # Or with auth provider for auto refresh
        >>> auth = DhanAuthProvider()
        >>> client = DhanHttpClient(
        ...     base_url="https://api.dhan.co",
        ...     access_token="your_token",
        ...     auth_provider=auth,
        ... )
    """
    
    def __init__(
        self,
        base_url: str,
        access_token: str,
        client_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retry_config: Optional[RetryConfig] = None,
        auth_provider: Optional["DhanAuthProvider"] = None,
    ) -> None:
        """
        Initialize the HTTP client.
        
        Args:
            base_url: Base URL for the Dhan API.
            access_token: Access token for authentication.
            client_id: Dhan client ID (required by Dhan v2 API headers).
            timeout: Request timeout in seconds.
            retry_config: Optional retry configuration.
            auth_provider: Optional auth provider for auto token refresh.
                When set, the client will automatically refresh the token
                on 401 errors and update its access token.
        """
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._client_id = client_id or ""
        self._timeout = timeout
        self._retry_config = retry_config or RetryConfig()
        self._auth_provider = auth_provider
        self._closed: bool = False
        # Per-event-loop session cache so sync (_run_async) and async (e.g. asyncio.run) use correct session
        self._sessions: Dict[int, aiohttp.ClientSession] = {}
        self._sessions_lock = threading.Lock()
        
        # Register callback for token updates if auth provider is set
        if self._auth_provider:
            # We'll handle this via the auth_provider callback mechanism
            pass
        
        logger.debug(
            f"DhanHttpClient initialized with base_url={base_url}, "
            f"timeout={timeout}s, max_retries={self._retry_config.max_retries}, "
            f"auth_provider={'yes' if auth_provider else 'no'}"
        )
    
    @property
    def base_url(self) -> str:
        """Get the base URL."""
        return self._base_url
    
    @property
    def access_token(self) -> str:
        """Get the access token."""
        return self._access_token
    
    @property
    def is_closed(self) -> bool:
        """Check if the client is closed."""
        return self._closed
    
    def set_access_token(self, access_token: str) -> None:
        """
        Update the access token.
        
        Called by auth provider when token is refreshed.
        
        Args:
            access_token: New access token.
        """
        self._access_token = access_token
        with self._sessions_lock:
            for session in self._sessions.values():
                if session and not session.closed:
                    session._default_headers.update(self._get_headers())
        logger.debug("Access token updated in HTTP client")
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Get default headers for requests.
        
        Dhan v2 API requires 'access-token' and 'client-id' headers, not Authorization Bearer.
        """
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "DhanPythonClient/1.0",
            "access-token": self._access_token,
        }
        if self._client_id:
            headers["client-id"] = self._client_id
        return headers
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Get or create the aiohttp session for the current event loop.

        Uses a per-loop session cache so that sync calls (via _run_async in
        worker threads) and async calls (e.g. asyncio.run in main thread) each
        use a session bound to their own loop, avoiding "Timeout context
        manager should be used inside a task" and cross-loop use.

        Returns:
            The aiohttp ClientSession for the current loop.
        """
        loop = asyncio.get_running_loop()
        key = id(loop)

        with self._sessions_lock:
            session = self._sessions.get(key)
            if session is not None and not session.closed:
                return session
            # Prune closed sessions for this or other loops
            closed = [k for k, s in self._sessions.items() if s.closed]
            for k in closed:
                del self._sessions[k]

        timeout = aiohttp.ClientTimeout(total=self._timeout)
        session = aiohttp.ClientSession(
            timeout=timeout,
            headers=self._get_headers(),
        )

        with self._sessions_lock:
            self._sessions[key] = session

        return session
    
    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> HttpResponse:
        """
        Execute a GET request.
        
        Args:
            endpoint: API endpoint path (e.g., "/orders").
            params: Optional query parameters.
        
        Returns:
            HttpResponse with status code, data, and headers.
        
        Raises:
            DhanNetworkError: If network error occurs.
            DhanTimeoutError: If request times out.
            DhanRateLimitError: If rate limit exceeded.
        """
        request = HttpRequest(
            method="GET",
            endpoint=endpoint,
            params=params,
        )
        return await self.request(request)
    
    async def post(
        self,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None
    ) -> HttpResponse:
        """
        Execute a POST request.
        
        Args:
            endpoint: API endpoint path (e.g., "/orders").
            json: Optional JSON body.
        
        Returns:
            HttpResponse with status code, data, and headers.
        
        Raises:
            DhanNetworkError: If network error occurs.
            DhanTimeoutError: If request times out.
            DhanRateLimitError: If rate limit exceeded.
        """
        request = HttpRequest(
            method="POST",
            endpoint=endpoint,
            json=json,
        )
        return await self.request(request)

    async def delete(
        self,
        endpoint: str,
    ) -> HttpResponse:
        """
        Execute a DELETE request.

        Args:
            endpoint: API endpoint path (e.g., "/orders/{order_id}").

        Returns:
            HttpResponse with status code, data, and headers.

        Raises:
            DhanNetworkError: If network error occurs.
            DhanTimeoutError: If request times out.
        """
        request = HttpRequest(
            method="DELETE",
            endpoint=endpoint,
        )
        return await self.request(request)

    async def request(self, request: HttpRequest) -> HttpResponse:
        """
        Execute a generic HTTP request with retry logic.
        
        This method handles:
            - Proactive token refresh before expiry
            - Auto token refresh on 401 errors
            - Retry with exponential backoff for network errors
        
        Args:
            request: HttpRequest with method, endpoint, params, json, headers.
        
        Returns:
            HttpResponse with status code, data, and headers.
        
        Raises:
            DhanNetworkError: If network error occurs.
            DhanTimeoutError: If request times out.
            DhanRateLimitError: If rate limit exceeded.
            DhanTokenExpiredError: If token expired and cannot refresh.
        """
        # Proactive token refresh if auth provider is set
        if self._auth_provider:
            try:
                await self._auth_provider.ensure_valid_token()
                # Update our token if it changed
                if self._auth_provider.access_token != self._access_token:
                    self._access_token = self._auth_provider.access_token
            except DhanAuthError as e:
                logger.warning(f"Failed to ensure valid token: {e}")
                # Continue with current token, will handle 401 if it occurs
        
        # Callers should use endpoint paths from brokers.broker.dhan.domain.api_contracts
        url = f"{self._base_url}{request.endpoint}"
        method = request.method.upper()
        
        # Merge headers
        headers = self._get_headers()
        if request.headers:
            headers.update(request.headers)
        
        # Prepare request kwargs
        kwargs: Dict[str, Any] = {"headers": headers}
        if request.params:
            kwargs["params"] = request.params
        if request.json:
            # Dhan v2 API requires dhanClientId in every POST payload (per SDK dhan_http.py)
            payload = dict(request.json)
            if self._client_id:
                payload["dhanClientId"] = self._client_id
            kwargs["json"] = payload
        
        # Execute with retry (including auth retry)
        return await self._execute_with_retry(
            method=method,
            url=url,
            kwargs=kwargs,
            request=request,
        )
    
    async def _execute_with_retry(
        self,
        method: str,
        url: str,
        kwargs: Dict[str, Any],
        request: HttpRequest,
        is_auth_retry: bool = False,
    ) -> HttpResponse:
        """
        Execute request with retry logic and auth error handling.
        
        Args:
            method: HTTP method.
            url: Full URL.
            kwargs: Request kwargs.
            request: Original request for retry.
            is_auth_retry: Whether this is a retry after auth refresh.
        
        Returns:
            HttpResponse with status code, data, and headers.
        
        Raises:
            DhanNetworkError: If network error occurs.
            DhanTimeoutError: If request times out.
            DhanRateLimitError: If rate limit exceeded.
            DhanTokenExpiredError: If token expired and cannot refresh.
        """
        last_error: Optional[Exception] = None
        
        for attempt in range(self._retry_config.max_retries + 1):
            try:
                response = await self._execute_request(
                    method=method,
                    url=url,
                    **kwargs
                )
                return response
            
            except (DhanTokenExpiredError, DhanTokenInvalidError) as e:
                # Handle auth errors - try to refresh token once
                if not is_auth_retry and self._auth_provider:
                    logger.info(f"Auth error, attempting token refresh: {e}")
                    try:
                        refreshed = await self._auth_provider.handle_auth_error(e)
                        if refreshed:
                            # Update token and retry once
                            self._access_token = self._auth_provider.access_token
                            kwargs["headers"] = self._get_headers()
                            if request.headers:
                                kwargs["headers"].update(request.headers)
                            
                            logger.info("Token refreshed, retrying request")
                            return await self._execute_with_retry(
                                method=method,
                                url=url,
                                kwargs=kwargs,
                                request=request,
                                is_auth_retry=True,
                            )
                    except Exception:
                        logger.exception("Token refresh failed")
                
                # Cannot refresh or already retried - raise the error
                raise
                
            except (DhanTimeoutError, DhanRateLimitError) as e:
                # These errors should not be retried
                raise
                
            except DhanNetworkError as e:
                last_error = e
                if attempt < self._retry_config.max_retries:
                    delay = self._retry_config.get_delay(attempt)
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self._retry_config.max_retries + 1}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
                    
            except aiohttp.ClientError as e:
                last_error = e
                if attempt < self._retry_config.max_retries:
                    delay = self._retry_config.get_delay(attempt)
                    logger.warning(
                        f"Client error (attempt {attempt + 1}/{self._retry_config.max_retries + 1}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise DhanConnectionError(
                        message=f"Connection error: {e}",
                        code=ERROR_CODE_CONNECTION_ERROR,
                        details={"url": url, "error": str(e)},
                    )
        
        # Should not reach here, but raise last error if we do
        if last_error:
            raise last_error
        raise DhanNetworkError("Unknown error occurred")
    
    async def _execute_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> HttpResponse:
        """
        Execute a single HTTP request without retry.
        
        Args:
            method: HTTP method.
            url: Full URL.
            **kwargs: Additional request arguments.
        
        Returns:
            HttpResponse with status code, data, and headers.
        
        Raises:
            DhanNetworkError: If network error occurs.
            DhanTimeoutError: If request times out.
            DhanRateLimitError: If rate limit exceeded.
        """
        session = await self._get_session()
        cid = get_correlation_id()

        try:
            logger.debug(
                f"HTTP {method} {url}",
                extra={"correlation_id": cid, "http_method": method},
            )

            async with session.request(method, url, **kwargs) as response:
                # Get response headers
                response_headers = dict(response.headers)

                # Read response body
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    # Not JSON, get as text
                    text = await response.text()
                    data = {"raw": text} if text else {}

                # Log response
                logger.debug(
                    f"HTTP {method} {url} -> {response.status}",
                    extra={"correlation_id": cid, "status": response.status},
                )
                
                # Handle status codes
                if response.status == 200:
                    return HttpResponse(
                        status_code=response.status,
                        data=data,
                        headers=response_headers,
                    )
                
                # Handle rate limiting
                if response.status == 429:
                    retry_after = response_headers.get("Retry-After")
                    retry_seconds = int(retry_after) if retry_after else None
                    raise DhanRateLimitError(
                        message="Rate limit exceeded",
                        code=ERROR_CODE_RATE_LIMIT,
                        details={"url": url, "response": data},
                        retry_after=retry_seconds,
                    )
                
                # Handle timeout
                if response.status == 408:
                    raise DhanTimeoutError(
                        message="Request timed out",
                        code=ERROR_CODE_TIMEOUT,
                        details={"url": url, "response": data},
                        timeout_seconds=self._timeout,
                    )
                
                # Handle authentication errors
                if response.status == 401:
                    error_code = data.get("errorCode") or ERROR_CODE_INVALID_TOKEN
                    error_message = data.get("message") or "Invalid access token"
                    raise DhanTokenInvalidError(
                        message=error_message,
                        code=error_code,
                        details={"url": url, "response": data},
                    )
                
                if response.status == 403:
                    error_code = data.get("errorCode") or ERROR_CODE_TOKEN_EXPIRED
                    error_message = data.get("message") or "Token expired or access denied"
                    raise DhanTokenExpiredError(
                        message=error_message,
                        code=error_code,
                        details={"url": url, "response": data},
                    )
                
                # Handle server errors (may retry)
                if response.status >= 500:
                    raise DhanNetworkError(
                        message=f"Server error: {response.status}",
                        code=str(response.status),
                        details={"url": url, "response": data},
                    )
                
                # Handle other client errors
                if response.status >= 400:
                    error_code = data.get("errorCode")
                    error_message = data.get("message") or f"HTTP {response.status} (No message provided)"
                    
                    # Try to create specific error from response
                    if error_code:
                        raise create_error_from_response(
                            code=error_code,
                            message=error_message,
                            details={"url": url, "response": data},
                        )
                    
                    # Generic error
                    raise DhanError(
                        message=error_message,
                        code=str(response.status),
                        details={"url": url, "response": data},
                    )
                
                # Success for other 2xx status codes
                return HttpResponse(
                    status_code=response.status,
                    data=data,
                    headers=response_headers,
                )
                
        except asyncio.TimeoutError as e:
            raise DhanTimeoutError(
                message="Request timed out",
                code=ERROR_CODE_TIMEOUT,
                details={"url": url, "timeout": self._timeout},
                timeout_seconds=self._timeout,
            )
            
        except aiohttp.ClientConnectorError as e:
            raise DhanConnectionError(
                message=f"Failed to connect: {e}",
                code=ERROR_CODE_CONNECTION_ERROR,
                details={"url": url, "error": str(e)},
            )
            
        except aiohttp.ClientError as e:
            raise DhanNetworkError(
                message=f"Network error: {e}",
                code=ERROR_CODE_CONNECTION_ERROR,
                details={"url": url, "error": str(e)},
            )
    
    async def close(self) -> None:
        """
        Close the HTTP client and release resources.

        Closes all per-loop sessions in the cache.
        """
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            if session and not session.closed:
                await session.close()
        if sessions:
            logger.debug("DhanHttpClient sessions closed")
        self._closed = True
    
    async def __aenter__(self) -> "DhanHttpClient":
        """Enter async context manager."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        await self.close()
    
    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"DhanHttpClient(base_url={self._base_url!r}, "
            f"timeout={self._timeout}, closed={self._closed}, "
            f"auth_provider={'yes' if self._auth_provider else 'no'})"
        )
