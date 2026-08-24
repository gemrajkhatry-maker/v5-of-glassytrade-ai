"""
Dhan v2 API contract - Single source of truth for base URL and endpoint paths.

All Dhan REST API calls must use:
- Base URL from DHAN_API_V2_BASE_URL (or config.base_url that defaults to it).
- Endpoint path constants from this module (no raw strings in broker/facade).

Required headers for v2 (implemented in DhanHttpClient):
- access-token: JWT access token
- client-id: Dhan client ID

Do NOT use Authorization: Bearer. When Dhan changes base URL or paths (e.g. v3),
update this module only; broker and config consume it.
"""

from brokers.broker.dhan.domain.constants import API_BASE_URL, API_VERSION

# Base URL for Dhan v2 REST API (all endpoints below are relative to this).
DHAN_API_V2_BASE_URL: str = f"{API_BASE_URL}/{API_VERSION}"

# -----------------------------------------------------------------------------
# Market data
# -----------------------------------------------------------------------------
MARKETFEED_LTP: str = "/marketfeed/ltp"
MARKETFEED_OHLC: str = "/marketfeed/ohlc"
MARKETFEED_QUOTE: str = "/marketfeed/quote"
CHARTS_HISTORICAL: str = "/charts/historical"
CHARTS_INTRADAY: str = "/charts/intraday"
CHARTS_ROLLING_OPTION: str = "/charts/rollingoption"

# -----------------------------------------------------------------------------
# Option chain
# -----------------------------------------------------------------------------
OPTIONCHAIN: str = "/optionchain"
OPTIONCHAIN_EXPIRYLIST: str = "/optionchain/expirylist"

# -----------------------------------------------------------------------------
# Orders and positions
# -----------------------------------------------------------------------------
ORDERS: str = "/orders"
ORDERS_SLICING: str = "/orders/slicing"
ORDERS_BY_ID: str = "/orders/{order_id}"
POSITIONS: str = "/positions"

# -----------------------------------------------------------------------------
# Trades and P&L
# -----------------------------------------------------------------------------
TRADES: str = "/trades"
PNL: str = "/pnl"

# -----------------------------------------------------------------------------
# Authentication (separate host from main API)
# -----------------------------------------------------------------------------
AUTH_GENERATE_TOKEN_URL: str = "https://auth.dhan.co/app/generateAccessToken"
RENEW_TOKEN_URL: str = f"{DHAN_API_V2_BASE_URL}/RenewToken"
