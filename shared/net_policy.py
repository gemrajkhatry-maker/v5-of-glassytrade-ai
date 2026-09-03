"""Sole timeout/retry/backoff owner. Frontend NETWORK_CONFIG mirrors these values. (REF-04)"""
from __future__ import annotations

DEFAULT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BACKOFF_FACTOR: float = 0.5
DEFAULT_RETRY_MAX_DELAY_SECONDS: float = 30.0
WS_PING_INTERVAL_SECONDS: float = 30.0
WS_RECONNECT_DELAY_SECONDS: float = 5.0
WS_MAX_RECONNECT_ATTEMPTS: int = 30
INSTRUMENT_CACHE_TTL_SECONDS: int = 86400

def capped_exp_delay(attempt: int, base: float = DEFAULT_RETRY_BACKOFF_FACTOR, cap: float = DEFAULT_RETRY_MAX_DELAY_SECONDS) -> float:
    return min(base * (2 ** attempt), cap)
