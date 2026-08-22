"""Canonical broker REST/WebSocket endpoint constants.

Previously the same base URLs and ``authorize`` paths were hardcoded in each
broker's client, adapter ``from_fetch`` defaults, and the trading runtime's
env-driven live builder. Centralizing them here means one logical change
(e.g. a version bump) touches a single file, and the client/adapter/runtime
can never drift.

Live runtime endpoints still allow env overrides (sandbox / proxies) — the
defaults below are the production contracts.
"""

from __future__ import annotations

# --- Dhan REST + WebSocket ------------------------------------------------

DHAN_REST_BASE_URL = "https://api.dhan.co/v2"
DHAN_ORDER_UPDATE_WS_URL = "wss://api-feed.dhan.co/v2/orderUpdate"
DHAN_MARKET_DATA_WS_URL = "wss://api-feed.dhan.co"
DHAN_DEPTH_20_WS_URL = "wss://depth-api-feed.dhan.co/twentydepth"

# --- Upstox REST + WebSocket ----------------------------------------------

UPSTOX_REST_BASE_URL = "https://api.upstox.com/v2"
UPSTOX_REST_HFT_BASE_URL = "https://api-hft.upstox.com/v3"
UPSTOX_REST_V3_BASE_URL = "https://api.upstox.com/v3"

# Upstox feed-authorize path (socket URL is returned per-request).
UPSTOX_MARKET_DATA_AUTHORIZE_PATH = "/feed/market-data-feed/authorize"
UPSTOX_PORTFOLIO_AUTHORIZE_PATH = "/feed/portfolio-stream-feed/authorize"

# Upstox OAuth token endpoint (used by the shared token lifecycle).
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


__all__ = [
    "DHAN_DEPTH_20_WS_URL",
    "DHAN_MARKET_DATA_WS_URL",
    "DHAN_ORDER_UPDATE_WS_URL",
    "DHAN_REST_BASE_URL",
    "UPSTOX_MARKET_DATA_AUTHORIZE_PATH",
    "UPSTOX_PORTFOLIO_AUTHORIZE_PATH",
    "UPSTOX_REST_BASE_URL",
    "UPSTOX_REST_HFT_BASE_URL",
    "UPSTOX_REST_V3_BASE_URL",
    "UPSTOX_TOKEN_URL",
]
