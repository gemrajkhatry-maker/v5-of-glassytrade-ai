"""
Dhan Domain Errors - Error hierarchy for Dhan broker operations.

This module defines a comprehensive error hierarchy for handling all
Dhan-specific error conditions. All errors inherit from DhanError
which provides code, message, and context details.

No external dependencies except standard library.
"""

from typing import Any, Dict, Optional


class DhanError(Exception):
    """
    Base error for all Dhan-related errors.
    
    All Dhan-specific errors inherit from this class, providing
    consistent error handling with error codes, messages, and context.
    
    Attributes:
        message: Human-readable error message.
        code: Optional error code for programmatic handling.
        details: Optional dictionary with additional context.
    
    Example:
        >>> try:
        ...     raise DhanError("Connection failed", code="DH-3003", details={"url": "https://api.dhan.co"})
        ... except DhanError as e:
        ...     print(f"Error {e.code}: {e.message}")
        ...     print(f"Details: {e.details}")
        Error DH-3003: Connection failed
        Details: {'url': 'https://api.dhan.co'}
    """
    
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Initialize DhanError.
        
        Args:
            message: Human-readable error message.
            code: Optional error code for programmatic handling.
            details: Optional dictionary with additional context.
        """
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)
    
    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message
    
    def __repr__(self) -> str:
        """Return repr of the error."""
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r}, details={self.details!r})"


# =============================================================================
# Authentication Errors
# =============================================================================

class DhanAuthError(DhanError):
    """
    Base class for authentication-related errors.
    
    Raised when there are issues with authentication credentials,
    tokens, or access permissions.
    """
    pass


class DhanTokenExpiredError(DhanAuthError):
    """
    Token has expired and needs refresh.
    
    This error indicates that the access token has expired and
    needs to be refreshed using the refresh token or re-authentication.
    
    Attributes:
        expired_at: Optional timestamp when the token expired.
    """
    
    def __init__(
        self,
        message: str = "Access token has expired",
        code: Optional[str] = "DH-1002",
        details: Optional[Dict[str, Any]] = None,
        expired_at: Optional[str] = None
    ) -> None:
        super().__init__(message, code, details)
        self.expired_at = expired_at


class DhanTokenInvalidError(DhanAuthError):
    """
    Token is invalid.
    
    This error indicates that the access token is malformed,
    revoked, or otherwise invalid.
    """
    
    def __init__(
        self,
        message: str = "Access token is invalid",
        code: Optional[str] = "DH-1001",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


class DhanAccessDeniedError(DhanAuthError):
    """
    Access denied to the requested resource.
    
    This error indicates that the user does not have permission
    to access the requested resource or perform the requested action.
    """
    
    def __init__(
        self,
        message: str = "Access denied",
        code: Optional[str] = "DH-1003",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


# =============================================================================
# Network Errors
# =============================================================================

class DhanNetworkError(DhanError):
    """
    Base class for network-related errors.
    
    Raised when there are issues with network connectivity,
    timeouts, or communication with the Dhan API.
    """
    pass


class DhanConnectionError(DhanNetworkError):
    """
    Failed to connect to Dhan API.
    
    This error indicates that a connection to the Dhan API
    could not be established.
    """
    
    def __init__(
        self,
        message: str = "Failed to connect to Dhan API",
        code: Optional[str] = "DH-3003",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


class DhanTimeoutError(DhanNetworkError):
    """
    Request timed out.
    
    This error indicates that a request to the Dhan API
    timed out before receiving a response.
    
    Attributes:
        timeout_seconds: The timeout duration that was exceeded.
    """
    
    def __init__(
        self,
        message: str = "Request timed out",
        code: Optional[str] = "DH-3002",
        details: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None
    ) -> None:
        super().__init__(message, code, details)
        self.timeout_seconds = timeout_seconds


class DhanRateLimitError(DhanNetworkError):
    """
    Rate limit exceeded.
    
    This error indicates that the rate limit for the Dhan API
    has been exceeded. The client should wait before retrying.
    
    Attributes:
        retry_after: Optional number of seconds to wait before retrying.
    """
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        code: Optional[str] = "DH-3001",
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None
    ) -> None:
        super().__init__(message, code, details)
        self.retry_after = retry_after


# =============================================================================
# Market Data Errors
# =============================================================================

class DhanMarketDataError(DhanError):
    """
    Base class for market data retrieval errors.
    
    Raised when there are issues retrieving market data from
    the Dhan API.
    """
    pass


class DhanSymbolNotFoundError(DhanMarketDataError):
    """
    Symbol not found in instrument master.
    
    This error indicates that the requested symbol could not
    be found in the Dhan instrument master.
    
    Attributes:
        symbol: The symbol that was not found.
        exchange: The exchange where the symbol was searched.
    """
    
    def __init__(
        self,
        message: str = "Symbol not found",
        code: Optional[str] = "DH-2001",
        details: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None
    ) -> None:
        super().__init__(message, code, details)
        self.symbol = symbol
        self.exchange = exchange


class DhanInvalidExchangeError(DhanMarketDataError):
    """
    Invalid exchange specified.
    
    This error indicates that the specified exchange is not
    supported or is invalid for the requested operation.
    """
    
    def __init__(
        self,
        message: str = "Invalid exchange specified",
        code: Optional[str] = "DH-2002",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


class DhanHistoricalDataError(DhanMarketDataError):
    """
    Error retrieving historical data.

    This error indicates that there was an issue retrieving
    historical OHLCV data from the Dhan API.
    """
    pass


class DhanFeedNotSupportedError(DhanMarketDataError):
    """Feed type not supported for the given exchange segment.
    Raised when QUOTE or TICKER feed is requested for MCX instruments.
    Use stream_full() for MCX.
    """
    def __init__(self, message="Feed type not supported for this exchange",
                 code="DH-2003", details=None, feed_type=None, exchange=None):
        super().__init__(message, code, details)
        self.feed_type = feed_type
        self.exchange  = exchange


# =============================================================================
# Data Errors
# =============================================================================

class DhanDataError(DhanError):
    """
    Base class for data validation errors.
    
    Raised when there are issues with data validation or
    data integrity.
    """
    pass


class DhanInvalidDataError(DhanDataError):
    """
    Invalid data received from API.
    
    This error indicates that the data received from the
    Dhan API is invalid or malformed.
    """
    
    def __init__(
        self,
        message: str = "Invalid data received from API",
        code: Optional[str] = "DH-4001",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


class DhanMissingDataError(DhanDataError):
    """
    Required data is missing.
    
    This error indicates that required data is missing from
    the request or response.
    """
    
    def __init__(
        self,
        message: str = "Required data is missing",
        code: Optional[str] = "DH-4002",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


# =============================================================================
# Order Errors
# =============================================================================

class DhanOrderError(DhanError):
    """
    Base class for order-related errors.
    
    Raised when there are issues with order placement,
    modification, or cancellation.
    """
    pass


class DhanOrderRejectedError(DhanOrderError):
    """
    Order was rejected.
    
    This error indicates that an order was rejected by
    the exchange or broker.
    
    Attributes:
        order_id: The ID of the rejected order.
        rejection_reason: The reason for rejection.
    """
    
    def __init__(
        self,
        message: str = "Order was rejected",
        code: Optional[str] = "DH-5001",
        details: Optional[Dict[str, Any]] = None,
        order_id: Optional[str] = None,
        rejection_reason: Optional[str] = None
    ) -> None:
        super().__init__(message, code, details)
        self.order_id = order_id
        self.rejection_reason = rejection_reason


class DhanInsufficientMarginError(DhanOrderError):
    """
    Insufficient margin for order.
    
    This error indicates that there is insufficient margin
    available to place the order.
    
    Attributes:
        required_margin: The margin required for the order.
        available_margin: The margin currently available.
    """
    
    def __init__(
        self,
        message: str = "Insufficient margin for order",
        code: Optional[str] = "DH-5002",
        details: Optional[Dict[str, Any]] = None,
        required_margin: Optional[float] = None,
        available_margin: Optional[float] = None
    ) -> None:
        super().__init__(message, code, details)
        self.required_margin = required_margin
        self.available_margin = available_margin


class DhanInvalidOrderError(DhanOrderError):
    """
    Invalid order parameters.
    
    This error indicates that the order parameters are
    invalid or incomplete.
    """
    
    def __init__(
        self,
        message: str = "Invalid order parameters",
        code: Optional[str] = "DH-5003",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, details)


class DhanOrderNotFoundError(DhanOrderError):
    """
    Order not found.
    
    This error indicates that the specified order could
    not be found.
    
    Attributes:
        order_id: The ID of the order that was not found.
    """
    
    def __init__(
        self,
        message: str = "Order not found",
        code: Optional[str] = "DH-5004",
        details: Optional[Dict[str, Any]] = None,
        order_id: Optional[str] = None
    ) -> None:
        super().__init__(message, code, details)
        self.order_id = order_id


# =============================================================================
# Symbol Errors
# =============================================================================

class DhanSymbolError(DhanError):
    """
    Base class for symbol-related errors.
    
    Raised when there are issues with symbol resolution
    or mapping.
    """
    pass


class DhanSymbolMappingError(DhanSymbolError):
    """
    Error mapping symbol to security ID.
    
    This error indicates that there was an issue mapping
    a symbol to its Dhan security ID.
    """
    pass


class DhanInstrumentNotFoundError(DhanSymbolError):
    """
    Instrument not found in cache.
    
    This error indicates that the instrument could not
    be found in the local instrument cache.
    """
    pass


# =============================================================================
# WebSocket Errors
# =============================================================================

class DhanWebSocketError(DhanError):
    """
    Base class for WebSocket-related errors.
    
    Raised when there are issues with WebSocket connections
    or message handling.
    """
    pass


class DhanWebSocketConnectionError(DhanWebSocketError):
    """
    Failed to establish WebSocket connection.
    
    This error indicates that a WebSocket connection could
    not be established.
    """
    pass


class DhanWebSocketDisconnectedError(DhanWebSocketError):
    """
    WebSocket connection was unexpectedly disconnected.
    
    This error indicates that the WebSocket connection was
    disconnected unexpectedly.
    """
    pass


class DhanWebSocketMessageError(DhanWebSocketError):
    """
    Error parsing WebSocket message.
    
    This error indicates that there was an error parsing
    a message received over the WebSocket connection.
    """
    pass


# =============================================================================
# Configuration Errors
# =============================================================================

class DhanConfigError(DhanError, ValueError):
    """
    Configuration error.
    
    This error indicates that there is an issue with the
    Dhan broker configuration.
    """
    pass


class DhanMissingConfigError(DhanConfigError):
    """
    Missing required configuration.
    
    This error indicates that a required configuration
    parameter is missing.
    """
    pass


# =============================================================================
# Error Registry for lookup by code
# =============================================================================

ERROR_CODE_MAP: Dict[str, type] = {
    "DH-1001": DhanTokenInvalidError,
    "DH-1002": DhanTokenExpiredError,
    "DH-1003": DhanAccessDeniedError,
    "DH-2001": DhanSymbolNotFoundError,
    "DH-2002": DhanInvalidExchangeError,
    "DH-2003": DhanFeedNotSupportedError,
    "DH-3001": DhanRateLimitError,
    "DH-3002": DhanTimeoutError,
    "DH-3003": DhanConnectionError,
    "DH-4001": DhanInvalidDataError,
    "DH-4002": DhanMissingDataError,
    "DH-5001": DhanOrderRejectedError,
    "DH-5002": DhanInsufficientMarginError,
    "DH-5003": DhanInvalidOrderError,
    "DH-5004": DhanOrderNotFoundError,
}


def get_error_by_code(code: str) -> Optional[type]:
    """
    Get error class by error code.
    
    Args:
        code: The error code to look up.
    
    Returns:
        The error class for the given code, or None if not found.
    """
    return ERROR_CODE_MAP.get(code)


def create_error_from_response(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> DhanError:
    """
    Create an appropriate error instance from an API response.
    
    Args:
        code: The error code from the API response.
        message: The error message from the API response.
        details: Optional additional details from the response.
    
    Returns:
        An instance of the appropriate error class.
    """
    error_class = get_error_by_code(code)
    if error_class:
        return error_class(message=message, code=code, details=details)
    return DhanError(message=message, code=code, details=details)
