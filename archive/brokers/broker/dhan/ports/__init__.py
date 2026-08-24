"""
Dhan Port Layer - Protocol definitions for external dependencies.

This package defines the interfaces (protocols) that external implementations
must satisfy. These protocols enable dependency inversion and testability.

Public API:
    HTTP: IHttpClient, HttpRequest, HttpResponse
    WebSocket: IWebSocketClient, WSMessage
    Mapper: ISymbolMapper
    Auth: IAuthProvider
    Resilience: IRateLimiter, ICircuitBreaker

Example:
    >>> from brokers.broker.dhan.ports import IHttpClient, IWebSocketClient
    >>> 
    >>> # Check if an implementation satisfies the protocol
    >>> isinstance(my_http_client, IHttpClient)
    True
"""

# =============================================================================
# HTTP Port
# =============================================================================

from .http_port import (
    HttpRequest,
    HttpResponse,
    IHttpClient,
)

# =============================================================================
# WebSocket Port
# =============================================================================

from .websocket_port import (
    WSMessage,
    IWebSocketClient,
)

# =============================================================================
# Mapper Port
# =============================================================================

from .mapper_port import (
    ISymbolMapper,
)

# =============================================================================
# Auth Port
# =============================================================================

from .auth_port import (
    IAuthProvider,
)

# =============================================================================
# Resilience Port
# =============================================================================

from .resilience_port import (
    IRateLimiter,
    ICircuitBreaker,
)


# =============================================================================
# Public API - All exports
# =============================================================================

__all__ = [
    # HTTP
    "HttpRequest",
    "HttpResponse",
    "IHttpClient",
    
    # WebSocket
    "WSMessage",
    "IWebSocketClient",
    
    # Mapper
    "ISymbolMapper",
    
    # Auth
    "IAuthProvider",
    
    # Resilience
    "IRateLimiter",
    "ICircuitBreaker",
]
