"""
Dhan Infrastructure Layer - Concrete implementations of ports.

This package contains the infrastructure implementations for the Dhan broker.
These implementations handle external communication with the Dhan API.

Public API:
    HTTP: DhanHttpClient
    WebSocket: DhanWebSocketClient, DepthWebSocketClient
    Mapper: DhanSymbolMapper
    Auth: DhanAuthProvider
    Resilience: TokenBucketRateLimiter, DhanCircuitBreaker

Example:
    >>> from brokers.broker.dhan.infrastructure import (
    ...     DhanHttpClient,
    ...     DhanWebSocketClient,
    ...     DhanSymbolMapper,
    ... )
    >>>
    >>> # Create HTTP client
    >>> http_client = DhanHttpClient(
    ...     base_url="https://api.dhan.co",
    ...     access_token="your_token",
    ... )
    >>>
    >>> # Create WebSocket client
    >>> ws_client = DhanWebSocketClient(
    ...     ws_url="wss://api.dhan.co/ws",
    ...     access_token="your_token",
    ... )
"""

# =============================================================================
# HTTP Client
# =============================================================================

from .http_client import (
    RetryConfig,
    DhanHttpClient,
)

# Sync HTTP client (legacy/sync-only helper; main path uses async DhanHttpClient)
from .http_client_sync import (
    DhanHttpClientSync,
)

# =============================================================================
# WebSocket Client
# =============================================================================

from .websocket_client import (
    DhanWebSocketClient,
)
from .depth_websocket_client import (
    DepthWebSocketClient,
)

# =============================================================================
# Symbol Mapper
# =============================================================================

from .symbol_mapper import (
    DhanSymbolMapper,
)

# =============================================================================
# Auth Provider
# =============================================================================

from .auth_provider import (
    DhanAuthProvider,
)

from .totp_generator import (
    TOTPGenerator,
    TOTPGenerationError,
)

# =============================================================================
# Resilience
# =============================================================================

from .resilience import (
    TokenBucketRateLimiter,
    DhanCircuitBreaker,
    RateLimitConfig,
    DEFAULT_RATE_LIMITS,
)
from shared.resilience import CircuitBreakerConfig


# =============================================================================
# Public API - All exports
# =============================================================================

__all__ = [
    # HTTP
    "RetryConfig",
    "DhanHttpClient",
    "DhanHttpClientSync",
    # WebSocket
    "DhanWebSocketClient",
    "DepthWebSocketClient",
    # Mapper
    "DhanSymbolMapper",
    # Auth
    "DhanAuthProvider",
    "TOTPGenerator",
    "TOTPGenerationError",
    # Resilience
    "TokenBucketRateLimiter",
    "DhanCircuitBreaker",
    "RateLimitConfig",
    "DEFAULT_RATE_LIMITS",
    "CircuitBreakerConfig",
]
