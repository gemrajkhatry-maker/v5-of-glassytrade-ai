"""
Dhan Domain Constants - API URLs, exchange segment IDs, and other constants.

This module contains all constants specific to the Dhan broker API.
No external dependencies except standard library.
"""

# Lot-size source of truth lives in quant.contracts.instrument_registry.
from quant.contracts.instrument_registry import DEFAULT_REGISTRY as _REG

# Timeout/retry/backoff/WS/cache policy lives in shared.net_policy;
# re-exported here so existing importers keep working unchanged.
from shared.net_policy import (  # noqa: F401
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_FACTOR,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    INSTRUMENT_CACHE_TTL_SECONDS,
    WS_MAX_RECONNECT_ATTEMPTS,
    WS_PING_INTERVAL_SECONDS,
    WS_RECONNECT_DELAY_SECONDS,
)

# =============================================================================
# API Configuration
# =============================================================================

API_BASE_URL: str = "https://api.dhan.co"
API_VERSION: str = "v2"
WS_URL: str = "wss://api-feed.dhan.co"  # auth params appended at connect time: ?version=2&token=...&clientId=...&authType=2

# Full Market Depth WebSocket endpoints (separate servers from regular feed)
# Auth URL format: ?token=<TOKEN>&clientId=<CLIENT_ID>&authType=2  (no version=2)
WS_URL_DEPTH_20: str = "wss://depth-api-feed.dhan.co/twentydepth"    # 20-level depth, up to 50 instruments
WS_URL_DEPTH_200: str = "wss://full-depth-api.dhan.co/twohundreddepth"  # 200-level depth, 1 instrument only

# Full API URL with version
API_URL: str = f"{API_BASE_URL}/{API_VERSION}"


# =============================================================================
# Exchange Segment IDs (Dhan-specific codes)
# =============================================================================

# Exchange segment IDs used in Dhan API
NSE_CASH: int = 1  # NSE Equity
NSE_FNO: int = 2  # NSE Futures & Options
NSE_CURRENCY: int = 3  # NSE Currency Derivatives
BSE_CASH: int = 4  # BSE Equity
MCX: int = 5  # MCX Commodities
BSE_FNO: int = 12  # BSE Futures & Options
IDX_I: int = 6  # NSE Indices


# =============================================================================
# Instrument Types (Dhan-specific codes)
# =============================================================================

# Instrument type IDs used in Dhan API
EQUITY: int = 1
FUTURES: int = 2
OPTIONS: int = 3
CURRENCY: int = 4
COMMODITY: int = 5


# =============================================================================
# Order Status Codes
# =============================================================================

# Order status codes returned by Dhan API
ORDER_STATUS_PENDING: str = "PENDING"
ORDER_STATUS_OPEN: str = "TRANSIT"  # Dhan uses TRANSIT for open orders
ORDER_STATUS_PARTIALLY_FILLED: str = "PARTIALLY_FILLED"
ORDER_STATUS_FILLED: str = "TRADED"  # Dhan uses TRADED for filled orders
ORDER_STATUS_CANCELLED: str = "CANCELLED"
ORDER_STATUS_REJECTED: str = "REJECTED"


# =============================================================================
# Transaction Types
# =============================================================================

TRANSACTION_TYPE_BUY: str = "BUY"
TRANSACTION_TYPE_SELL: str = "SELL"


# =============================================================================
# Product Types
# =============================================================================

PRODUCT_TYPE_INTRADAY: str = "I"  # Intraday / MIS
PRODUCT_TYPE_MARGIN: str = "M"  # Margin / NRML
PRODUCT_TYPE_CNC: str = "C"  # Cash and Carry
PRODUCT_TYPE_CO: str = "CO"  # Cover Order
PRODUCT_TYPE_BO: str = "BO"  # Bracket Order


# =============================================================================
# Order Types
# =============================================================================

ORDER_TYPE_MARKET: str = "MARKET"
ORDER_TYPE_LIMIT: str = "LIMIT"
ORDER_TYPE_STOP_LOSS: str = "SL"
ORDER_TYPE_STOP_LOSS_MARKET: str = "SL-M"


# =============================================================================
# Validity Types
# =============================================================================

VALIDITY_DAY: str = "DAY"
VALIDITY_IMMEDIATE: str = "IOC"  # Immediate or Cancel
VALIDITY_GOOD_TILL_CANCELLED: str = "GTC"


# =============================================================================
# WebSocket Feed Types
# =============================================================================

# Feed type codes for WebSocket subscriptions (regular feed)
FEED_TYPE_TICKER: int = 15  # LTP only
FEED_TYPE_QUOTE: int = 17  # LTP + OHLC + Volume
# Full feed = Quote + 5-level depth per Dhan's spec. Was 17 (silently a QUOTE
# subscription — depth packets never subscribed), contradicting the documented
# code 21 and streaming_service's own comment.
FEED_TYPE_FULL: int = 21
FEED_TYPE_FULL_DEPTH: int = 20  # 20-level depth (depth-only endpoint)

# Full Market Depth WebSocket — subscription and response codes
# These apply to both WS_URL_DEPTH_20 and WS_URL_DEPTH_200 endpoints
DEPTH_REQUEST_CODE: int = 23   # RequestCode used to subscribe on depth feeds
DEPTH_UNSUBSCRIBE_CODE: int = 12  # RequestCode to disconnect/unsubscribe

# Response codes inside binary depth packets (byte [2] of the 12-byte header)
DEPTH_RC_BID: int = 41   # Bid / Buy side packet
DEPTH_RC_ASK: int = 51   # Ask / Sell side packet
DEPTH_RC_DISCONNECT: int = 50  # Server-initiated disconnect


# =============================================================================
# Lot Sizes by Exchange Segment
# =============================================================================

LOT_SIZES: dict[str, int] = {
    **{s.root: s.lot_size for s in _REG.specs()},
    # --- Non-registry extras: NSE F&O stocks (lots vary; registry covers indices/MCX only)
    "RELIANCE": 250,
    "TCS": 150,
    "INFY": 600,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 1500,
    "TATAMOTORS": 1500,
    "AXISBANK": 1200,
    "BAJFINANCE": 125,
    "MARUTI": 100,
    "HINDUNILVR": 300,
    "KOTAKBANK": 300,
    "LT": 250,
    "BHARTIARTL": 750,
    "WIPRO": 1000,
    "TATASTEEL": 2500,
    "ADANIENT": 250,
    "NTPC": 2300,
    "POWERGRID": 2600,
    "ULTRACEMCO": 150,
}


# =============================================================================
# Strike Step Sizes by Underlying
# =============================================================================

# Strike price step sizes for major underlyings
STRIKE_STEPS: dict[str, float] = {
    # NSE F&O Indices
    "NIFTY": 50.0,
    "BANKNIFTY": 100.0,
    "FINNIFTY": 50.0,
    "MIDCPNIFTY": 25.0,
    "SENSEX": 100.0,
    "BANKEX": 100.0,
    # Default for stocks
    "DEFAULT": 5.0,
}


# =============================================================================
# Rate Limit Defaults
# =============================================================================

# Default rate limits per category (requests per second)
RATE_LIMIT_MARKET_DATA: int = 10
RATE_LIMIT_HISTORICAL: int = 10  # Dhan API limit: 10 req/sec for historical data
RATE_LIMIT_ORDERS: int = 5
RATE_LIMIT_DEFAULT: int = 10
RATE_LIMIT_OPTION_CHAIN: float = 0.33  # Dhan docs: 1 unique request per 3 seconds

# Burst limits
RATE_BURST_MARKET_DATA: int = 20
RATE_BURST_HISTORICAL: int = 10
RATE_BURST_ORDERS: int = 10
RATE_BURST_DEFAULT: int = 20
RATE_BURST_OPTION_CHAIN: int = 1  # No burst — strict 1 per 3s


# =============================================================================
# Historical Data Limits
# =============================================================================

# Maximum days allowed in a single historical data request
# Dhan API limit: max 90 days of data in one call
HISTORICAL_MAX_DAYS: int = 90


# =============================================================================
# Timeouts and Retries
# =============================================================================

# Default timeout in seconds / retry configuration — owned by shared.net_policy
# (names re-exported here so existing importers keep working unchanged)

# TOTP time window in seconds (standard TOTP interval)
TOTP_TIME_WINDOW_SECONDS: int = 30


# =============================================================================
# WebSocket Configuration
# =============================================================================

# WebSocket ping/pong, reconnection — owned by shared.net_policy
# (names re-exported here so existing importers keep working unchanged)


# =============================================================================
# Cache Configuration
# =============================================================================

# Instrument cache TTL in seconds (24 hours) — owned by shared.net_policy
# (name re-exported here so existing importers keep working unchanged)


# =============================================================================
# Error Codes (Dhan API specific)
# =============================================================================

# Dhan API error codes
ERROR_CODE_INVALID_TOKEN: str = "DH-1001"
ERROR_CODE_TOKEN_EXPIRED: str = "DH-1002"
ERROR_CODE_INVALID_ACCESS: str = "DH-1003"
ERROR_CODE_SYMBOL_NOT_FOUND: str = "DH-2001"
ERROR_CODE_INVALID_EXCHANGE: str = "DH-2002"
ERROR_CODE_RATE_LIMIT: str = "DH-3001"
ERROR_CODE_TIMEOUT: str = "DH-3002"
ERROR_CODE_CONNECTION_ERROR: str = "DH-3003"
ERROR_CODE_INVALID_DATA: str = "DH-4001"
ERROR_CODE_MISSING_DATA: str = "DH-4002"
ERROR_CODE_ORDER_REJECTED: str = "DH-5001"
ERROR_CODE_INSUFFICIENT_MARGIN: str = "DH-5002"
ERROR_CODE_INVALID_ORDER: str = "DH-5003"


# =============================================================================
# Known Index Underlyings (single source of truth — used by broker + services)
# =============================================================================

INDEX_UNDERLYINGS: frozenset = frozenset({
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX",
    "NIFTY 50", "NIFTY BANK",
})
