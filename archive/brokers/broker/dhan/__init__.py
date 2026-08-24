"""
Dhan Broker - Clean Architecture Implementation.

This package provides a clean, fault-tolerant implementation of the Dhan broker
without depending on dhanhq_custom.

Usage:
    from brokers.broker.dhan import DhanBroker, DhanConfig
    
    # Create broker with factory method
    broker = DhanBroker.create(
        client_id="your_client_id",
        access_token="your_access_token"
    )
    
    # Or from environment
    config = DhanConfig.from_env()
    broker = DhanBroker(config=config)
"""

# Application Layer (main public API)
from brokers.broker.dhan.application import (
    DhanBroker,
    DhanConfig,
    DhanConverter,
    to_segment,
    DhanExchangeResolver,
    ResolvedExchange,
)

# Domain Layer (for advanced usage)
from brokers.broker.dhan.domain import (
    # Entities
    DhanInstrument,
    DhanQuote,
    DhanTick,
    DhanOption,
    DhanOptionChain,
    DhanOrder,
    DhanPosition,
    
    # Value Objects
    ExchangeSegment,
    InstrumentTypeVO,
    DepthLevel,
    MarketDepth,
    OHLC,
    Greeks,
    
    # Enums
    InstrumentTypeEnum,
    FeedType,
    ProductType,
    OrderValidity,
    
    # Errors
    DhanError,
    DhanAuthError,
    DhanNetworkError,
    DhanRateLimitError,
    DhanMarketDataError,
    DhanOrderError,
    
    # Constants
    API_BASE_URL,
    WS_URL,
    API_VERSION,
)

# Port Layer (for custom implementations)
from brokers.broker.dhan.ports import (
    IHttpClient,
    IWebSocketClient,
    ISymbolMapper,
    IAuthProvider,
    IRateLimiter,
    ICircuitBreaker,
    HttpRequest,
    HttpResponse,
    WSMessage,
)

# Infrastructure Layer (for direct usage)
from brokers.broker.dhan.infrastructure import (
    DhanHttpClient,
    DhanWebSocketClient,
    DhanSymbolMapper,
    DhanAuthProvider,
    TokenBucketRateLimiter,
    DhanCircuitBreaker,
    RetryConfig,
)

__all__ = [
    # Application
    "DhanBroker",
    "DhanConfig",
    "DhanConverter",
    "to_segment",
    
    # Exchange Resolver
    "DhanExchangeResolver",
    "ResolvedExchange",
    
    # Domain Entities
    "DhanInstrument",
    "DhanQuote",
    "DhanTick",
    "DhanOption",
    "DhanOptionChain",
    "DhanOrder",
    "DhanPosition",
    
    # Domain Value Objects
    "ExchangeSegment",
    "InstrumentTypeVO",
    "DepthLevel",
    "MarketDepth",
    "OHLC",
    "Greeks",
    
    # Domain Enums
    "InstrumentTypeEnum",
    "FeedType",
    "ProductType",
    "OrderValidity",
    
    # Domain Errors
    "DhanError",
    "DhanAuthError",
    "DhanNetworkError",
    "DhanRateLimitError",
    "DhanMarketDataError",
    "DhanOrderError",
    
    # Domain Constants
    "API_BASE_URL",
    "WS_URL",
    "API_VERSION",
    
    # Ports
    "IHttpClient",
    "IWebSocketClient",
    "ISymbolMapper",
    "IAuthProvider",
    "IRateLimiter",
    "ICircuitBreaker",
    "HttpRequest",
    "HttpResponse",
    "WSMessage",
    
    # Infrastructure
    "DhanHttpClient",
    "DhanWebSocketClient",
    "DhanSymbolMapper",
    "DhanAuthProvider",
    "TokenBucketRateLimiter",
    "DhanCircuitBreaker",
    "RetryConfig",
]
