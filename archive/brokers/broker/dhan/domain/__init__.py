"""
Dhan Domain Layer - Core domain entities, value objects, errors, and constants.

This package contains the pure domain layer for the Dhan broker implementation.
All components are immutable and have no external dependencies.

Public API:
    Constants: API URLs, exchange segment IDs, instrument types, etc.
    Errors: Complete error hierarchy for Dhan operations.
    Value Objects: ExchangeSegment, InstrumentType, DepthLevel, etc.
    Entities: DhanInstrument, DhanQuote, DhanTick, DhanOption, DhanOptionChain.

Example:
    >>> from brokers.broker.dhan.domain import (
    ...     DhanInstrument,
    ...     DhanQuote,
    ...     DhanError,
    ...     ExchangeSegment,
    ...     API_BASE_URL,
    ... )
    >>> 
    >>> # Create an instrument
    >>> instrument = DhanInstrument(
    ...     security_id="12345",
    ...     trading_symbol="NIFTY23FEB18000CE",
    ...     symbol="NIFTY",
    ...     exchange_segment=ExchangeSegment.NSE_FNO,
    ...     instrument_type=InstrumentTypeEnum.INDEX_OPTION,
    ... )
"""

# =============================================================================
# Constants
# =============================================================================

from .api_contracts import (
    DHAN_API_V2_BASE_URL,
    MARKETFEED_LTP,
    MARKETFEED_OHLC,
    MARKETFEED_QUOTE,
    CHARTS_HISTORICAL,
    CHARTS_INTRADAY,
    CHARTS_ROLLING_OPTION,
    OPTIONCHAIN,
    OPTIONCHAIN_EXPIRYLIST,
    ORDERS,
    ORDERS_SLICING,
    ORDERS_BY_ID,
    POSITIONS,
    TRADES,
    PNL,
    AUTH_GENERATE_TOKEN_URL,
    RENEW_TOKEN_URL,
)
from .constants import (
    # API Configuration
    API_BASE_URL,
    API_VERSION,
    WS_URL,
    WS_URL_DEPTH_20,
    WS_URL_DEPTH_200,
    API_URL,
    DEPTH_REQUEST_CODE,
    DEPTH_UNSUBSCRIBE_CODE,
    DEPTH_RC_BID,
    DEPTH_RC_ASK,
    DEPTH_RC_DISCONNECT,
    
    # Exchange Segment IDs
    NSE_CASH,
    NSE_FNO,
    NSE_CURRENCY,
    BSE_CASH,
    MCX,
    BSE_FNO,
    
    # Instrument Types
    EQUITY,
    FUTURES,
    OPTIONS,
    CURRENCY,
    COMMODITY,
    
    # Order Status Codes
    ORDER_STATUS_PENDING,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_REJECTED,
    
    # Transaction Types
    TRANSACTION_TYPE_BUY,
    TRANSACTION_TYPE_SELL,
    
    # Product Types
    PRODUCT_TYPE_INTRADAY,
    PRODUCT_TYPE_MARGIN,
    PRODUCT_TYPE_CNC,
    PRODUCT_TYPE_CO,
    PRODUCT_TYPE_BO,
    
    # Order Types
    ORDER_TYPE_MARKET,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_STOP_LOSS,
    ORDER_TYPE_STOP_LOSS_MARKET,
    
    # Validity Types
    VALIDITY_DAY,
    VALIDITY_IMMEDIATE,
    VALIDITY_GOOD_TILL_CANCELLED,
    
    # WebSocket Feed Types
    FEED_TYPE_TICKER,
    FEED_TYPE_QUOTE,
    FEED_TYPE_FULL,
    FEED_TYPE_FULL_DEPTH,
    
    # Lot Sizes and Strike Steps
    LOT_SIZES,
    STRIKE_STEPS,
    
    # Rate Limits
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
    
    # Historical Data Limits
    HISTORICAL_MAX_DAYS,
    
    # Timeouts and Retries
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    TOTP_TIME_WINDOW_SECONDS,
    
    # WebSocket Configuration
    WS_PING_INTERVAL_SECONDS,
    WS_RECONNECT_DELAY_SECONDS,
    WS_MAX_RECONNECT_ATTEMPTS,
    
    # Cache Configuration
    INSTRUMENT_CACHE_TTL_SECONDS,
    
    # Error Codes
    ERROR_CODE_INVALID_TOKEN,
    ERROR_CODE_TOKEN_EXPIRED,
    ERROR_CODE_INVALID_ACCESS,
    ERROR_CODE_SYMBOL_NOT_FOUND,
    ERROR_CODE_INVALID_EXCHANGE,
    ERROR_CODE_RATE_LIMIT,
    ERROR_CODE_TIMEOUT,
    ERROR_CODE_CONNECTION_ERROR,
    ERROR_CODE_INVALID_DATA,
    ERROR_CODE_MISSING_DATA,
    ERROR_CODE_ORDER_REJECTED,
    ERROR_CODE_INSUFFICIENT_MARGIN,
    ERROR_CODE_INVALID_ORDER,
)

# =============================================================================
# Errors
# =============================================================================

from .errors import (
    # Base Error
    DhanError,
    
    # Authentication Errors
    DhanAuthError,
    DhanTokenExpiredError,
    DhanTokenInvalidError,
    DhanAccessDeniedError,
    
    # Network Errors
    DhanNetworkError,
    DhanConnectionError,
    DhanTimeoutError,
    DhanRateLimitError,
    
    # Market Data Errors
    DhanMarketDataError,
    DhanSymbolNotFoundError,
    DhanInvalidExchangeError,
    DhanHistoricalDataError,
    DhanFeedNotSupportedError,

    # Data Errors
    DhanDataError,
    DhanInvalidDataError,
    DhanMissingDataError,
    
    # Order Errors
    DhanOrderError,
    DhanOrderRejectedError,
    DhanInsufficientMarginError,
    DhanInvalidOrderError,
    DhanOrderNotFoundError,
    
    # Symbol Errors
    DhanSymbolError,
    DhanSymbolMappingError,
    DhanInstrumentNotFoundError,
    
    # WebSocket Errors
    DhanWebSocketError,
    DhanWebSocketConnectionError,
    DhanWebSocketDisconnectedError,
    DhanWebSocketMessageError,
    
    # Configuration Errors
    DhanConfigError,
    DhanMissingConfigError,
    
    # Error Utilities
    ERROR_CODE_MAP,
    get_error_by_code,
    create_error_from_response,
)

# =============================================================================
# Value Objects
# =============================================================================

from .value_objects import (
    # Enums
    InstrumentTypeEnum,
    FeedType,
    ProductType,
    OrderValidity,
    OptionType,
    
    # Frozen Dataclasses
    ExchangeSegment,
    InstrumentTypeVO,
    DepthLevel,
    MarketDepth,
    OHLC,
    Greeks,
)

# =============================================================================
# Entities
# =============================================================================

from .entities import (
    # Core Entities
    DhanInstrument,
    DhanQuote,
    DhanTick,
    
    # Option Entities
    DhanOption,
    DhanOptionChain,
    
    # Order Entities
    DhanOrder,
    DhanPosition,
)

from .segment_mapping import (
    exchange_to_segment_name,
    segment_name_to_exchange,
    exchange_to_option_chain_api_segment,
    resolve_dhan_instrument_type,
)

# =============================================================================
# Public API - All exports
# =============================================================================

__all__ = [
    # API contract (v2 base URL and endpoint paths)
    "DHAN_API_V2_BASE_URL",
    "MARKETFEED_LTP",
    "MARKETFEED_OHLC",
    "MARKETFEED_QUOTE",
    "CHARTS_HISTORICAL",
    "CHARTS_INTRADAY",
    "CHARTS_ROLLING_OPTION",
    "OPTIONCHAIN",
    "OPTIONCHAIN_EXPIRYLIST",
    "ORDERS",
    "ORDERS_SLICING",
    "ORDERS_BY_ID",
    "POSITIONS",
    "TRADES",
    "PNL",
    "AUTH_GENERATE_TOKEN_URL",
    "RENEW_TOKEN_URL",
    # Constants - API Configuration
    "API_BASE_URL",
    "API_VERSION",
    "WS_URL",
    "WS_URL_DEPTH_20",
    "WS_URL_DEPTH_200",
    "DEPTH_REQUEST_CODE",
    "DEPTH_UNSUBSCRIBE_CODE",
    "DEPTH_RC_BID",
    "DEPTH_RC_ASK",
    "DEPTH_RC_DISCONNECT",
    "API_URL",
    
    # Constants - Exchange Segment IDs
    "NSE_CASH",
    "NSE_FNO",
    "NSE_CURRENCY",
    "BSE_CASH",
    "MCX",
    "BSE_FNO",
    
    # Constants - Instrument Types
    "EQUITY",
    "FUTURES",
    "OPTIONS",
    "CURRENCY",
    "COMMODITY",
    
    # Constants - Order Status
    "ORDER_STATUS_PENDING",
    "ORDER_STATUS_OPEN",
    "ORDER_STATUS_PARTIALLY_FILLED",
    "ORDER_STATUS_FILLED",
    "ORDER_STATUS_CANCELLED",
    "ORDER_STATUS_REJECTED",
    
    # Constants - Transaction Types
    "TRANSACTION_TYPE_BUY",
    "TRANSACTION_TYPE_SELL",
    
    # Constants - Product Types
    "PRODUCT_TYPE_INTRADAY",
    "PRODUCT_TYPE_MARGIN",
    "PRODUCT_TYPE_CNC",
    "PRODUCT_TYPE_CO",
    "PRODUCT_TYPE_BO",
    
    # Constants - Order Types
    "ORDER_TYPE_MARKET",
    "ORDER_TYPE_LIMIT",
    "ORDER_TYPE_STOP_LOSS",
    "ORDER_TYPE_STOP_LOSS_MARKET",
    
    # Constants - Validity Types
    "VALIDITY_DAY",
    "VALIDITY_IMMEDIATE",
    "VALIDITY_GOOD_TILL_CANCELLED",
    
    # Constants - WebSocket Feed Types
    "FEED_TYPE_TICKER",
    "FEED_TYPE_QUOTE",
    "FEED_TYPE_FULL",
    "FEED_TYPE_FULL_DEPTH",
    
    # Constants - Lot Sizes and Strike Steps
    "LOT_SIZES",
    "STRIKE_STEPS",
    
    # Constants - Rate Limits
    "RATE_LIMIT_MARKET_DATA",
    "RATE_LIMIT_HISTORICAL",
    "RATE_LIMIT_ORDERS",
    "RATE_LIMIT_DEFAULT",
    "RATE_LIMIT_OPTION_CHAIN",
    "RATE_BURST_MARKET_DATA",
    "RATE_BURST_HISTORICAL",
    "RATE_BURST_ORDERS",
    "RATE_BURST_DEFAULT",
    "RATE_BURST_OPTION_CHAIN",
    
    # Constants - Historical Data Limits
    "HISTORICAL_MAX_DAYS",
    
    # Constants - Timeouts
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_BACKOFF_FACTOR",
    "DEFAULT_RETRY_MAX_DELAY_SECONDS",
    "TOTP_TIME_WINDOW_SECONDS",
    
    # Constants - WebSocket
    "WS_PING_INTERVAL_SECONDS",
    "WS_RECONNECT_DELAY_SECONDS",
    "WS_MAX_RECONNECT_ATTEMPTS",
    
    # Constants - Cache
    "INSTRUMENT_CACHE_TTL_SECONDS",
    
    # Constants - Error Codes
    "ERROR_CODE_INVALID_TOKEN",
    "ERROR_CODE_TOKEN_EXPIRED",
    "ERROR_CODE_INVALID_ACCESS",
    "ERROR_CODE_SYMBOL_NOT_FOUND",
    "ERROR_CODE_INVALID_EXCHANGE",
    "ERROR_CODE_RATE_LIMIT",
    "ERROR_CODE_TIMEOUT",
    "ERROR_CODE_CONNECTION_ERROR",
    "ERROR_CODE_INVALID_DATA",
    "ERROR_CODE_MISSING_DATA",
    "ERROR_CODE_ORDER_REJECTED",
    "ERROR_CODE_INSUFFICIENT_MARGIN",
    "ERROR_CODE_INVALID_ORDER",
    
    # Errors - Base
    "DhanError",
    
    # Errors - Authentication
    "DhanAuthError",
    "DhanTokenExpiredError",
    "DhanTokenInvalidError",
    "DhanAccessDeniedError",
    
    # Errors - Network
    "DhanNetworkError",
    "DhanConnectionError",
    "DhanTimeoutError",
    "DhanRateLimitError",
    
    # Errors - Market Data
    "DhanMarketDataError",
    "DhanSymbolNotFoundError",
    "DhanInvalidExchangeError",
    "DhanHistoricalDataError",
    "DhanFeedNotSupportedError",

    # Errors - Data
    "DhanDataError",
    "DhanInvalidDataError",
    "DhanMissingDataError",
    
    # Errors - Order
    "DhanOrderError",
    "DhanOrderRejectedError",
    "DhanInsufficientMarginError",
    "DhanInvalidOrderError",
    "DhanOrderNotFoundError",
    
    # Errors - Symbol
    "DhanSymbolError",
    "DhanSymbolMappingError",
    "DhanInstrumentNotFoundError",
    
    # Errors - WebSocket
    "DhanWebSocketError",
    "DhanWebSocketConnectionError",
    "DhanWebSocketDisconnectedError",
    "DhanWebSocketMessageError",
    
    # Errors - Configuration
    "DhanConfigError",
    "DhanMissingConfigError",
    
    # Errors - Utilities
    "ERROR_CODE_MAP",
    "get_error_by_code",
    "create_error_from_response",
    
    # Value Objects - Enums
    "InstrumentTypeEnum",
    "FeedType",
    "ProductType",
    "OrderValidity",
    "OptionType",
    
    # Value Objects - Dataclasses
    "ExchangeSegment",
    "InstrumentTypeVO",
    "DepthLevel",
    "MarketDepth",
    "OHLC",
    "Greeks",
    
    # Entities - Core
    "DhanInstrument",
    "DhanQuote",
    "DhanTick",
    
    # Entities - Options
    "DhanOption",
    "DhanOptionChain",
    
    # Entities - Orders
    "DhanOrder",
    "DhanPosition",
    
    # Segment mapping (single source for Exchange <-> segment)
    "exchange_to_segment_name",
    "segment_name_to_exchange",
    "exchange_to_option_chain_api_segment",
    "resolve_dhan_instrument_type",
]
