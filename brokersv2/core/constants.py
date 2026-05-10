"""
Centralized constants for GlassyTrade brokersv2.

This module contains all hardcoded values that should be configurable
across the codebase. Values can be overridden via environment variables.

Categories:
- API URLs and endpoints
- WebSocket configuration
- Circuit breaker settings
- Retry policy defaults
- Cache defaults
- Timeouts and intervals
- Platform limits
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import FrozenSet


# =============================================================================
# API Configuration
# =============================================================================

class API:
    """API endpoint URLs and configuration."""
    
    # DhanHQ API base URLs (can be overridden via env)
    DHAN_BASE_URL: str = os.environ.get("DHAN_BASE_URL", "https://api.dhan.co/v2")
    DHAN_WS_URL: str = os.environ.get("DHAN_WS_URL", "wss://api.dhan.co/ws")
    
    # Default timeout for HTTP requests (seconds)
    DEFAULT_TIMEOUT: int = int(os.environ.get("DHAN_TIMEOUT", "30"))


# =============================================================================
# WebSocket Configuration
# =============================================================================

class WebSocket:
    """WebSocket connection settings."""
    
    # Heartbeat interval in seconds
    HEARTBEAT_INTERVAL: float = 10.0
    
    # Maximum reconnect attempts before giving up
    MAX_RECONNECT_ATTEMPTS: int = 10
    
    # Initial backoff delay in seconds (exponential backoff base)
    INITIAL_BACKOFF: float = 1.0
    
    # Maximum backoff delay in seconds
    MAX_BACKOFF: float = 60.0
    
    # Maximum concurrent connections (DhanHQ limit)
    MAX_CONNECTIONS: int = 5
    
    # Maximum instruments per connection (DhanHQ limit)
    MAX_INSTRUMENTS_PER_CONNECTION: int = 5000
    
    # Maximum instruments per subscribe message (API limit)
    MAX_INSTRUMENTS_PER_SUBSCRIBE: int = 100


# =============================================================================
# Circuit Breaker Settings
# =============================================================================

class CircuitBreaker:
    """Circuit breaker configuration."""
    
    # Number of failures before opening the circuit
    FAILURE_THRESHOLD: int = 5
    
    # Time to wait before attempting recovery (seconds)
    RECOVERY_TIMEOUT: float = 60.0


# =============================================================================
# Retry Policy Defaults
# =============================================================================

class Retry:
    """Retry policy configuration."""
    
    # Maximum number of retry attempts
    MAX_RETRIES: int = 3
    
    # Base delay between retries (seconds)
    BASE_DELAY: float = 1.0
    
    # Maximum delay between retries (seconds)
    MAX_DELAY: float = 30.0
    
    # Exponential backoff base
    EXPONENTIAL_BASE: float = 2.0
    
    # Jitter for backoff randomization (factor of delay)
    JITTER_FACTOR: float = 0.1
    
    # Whether to enable jitter by default
    ENABLE_JITTER: bool = True
    
    # Default retryable exceptions for network operations
    DEFAULT_RETRYABLE_EXCEPTIONS: FrozenSet = frozenset({
        TimeoutError,
        asyncio.TimeoutError,
        ConnectionError,
        OSError,
    })


# =============================================================================
# Cache Configuration
# =============================================================================

class Cache:
    """Cache configuration."""
    
    # Default LRU cache size
    DEFAULT_MAX_SIZE: int = 1000
    
    # Default TTL for cache entries (seconds)
    DEFAULT_TTL: int = 3600  # 1 hour


# =============================================================================
# Historical Data Router Configuration
# =============================================================================

class HistoricalRouter:
    """Historical data router settings."""
    
    # Timeout for primary provider requests (seconds)
    PRIMARY_TIMEOUT: float = 10.0
    
    # Timeout for fallback provider requests (seconds)
    FALLBACK_TIMEOUT: float = 15.0


# =============================================================================
# Object Pool Configuration
# =============================================================================

class ObjectPool:
    """Object pool defaults."""
    
    # Default pool size for object reuse
    DEFAULT_POOL_SIZE: int = 1000


# =============================================================================
# Ring Buffer Configuration
# =============================================================================

class RingBuffer:
    """Ring buffer defaults."""
    
    # Default capacity for ring buffers
    DEFAULT_CAPACITY: int = 10000


# =============================================================================
# Rate Limiter Configuration
# =============================================================================

class RateLimiter:
    """Rate limiter settings."""
    
    # Default requests per second
    DEFAULT_RATE: float = 10.0
    
    # Burst capacity
    DEFAULT_BURST: int = 20


# =============================================================================
# Gateway Server Configuration
# =============================================================================

class Gateway:
    """Gateway server defaults."""
    
    # Default host
    DEFAULT_HOST: str = "0.0.0.0"
    
    # Default port
    DEFAULT_PORT: int = 9090
    
    # Default debug mode
    DEFAULT_DEBUG: bool = False
    
    # Default dry run mode
    DEFAULT_DRY_RUN: bool = False


# =============================================================================
# Idempotency Configuration
# =============================================================================

class Idempotency:
    """Idempotency settings."""
    
    # Default TTL for idempotency records (seconds)
    DEFAULT_TTL: int = 3600  # 1 hour
    
    # Default max records to store
    DEFAULT_MAX_RECORDS: int = 10000


# =============================================================================
# Position Reconciliation Configuration
# =============================================================================

class PositionReconciliation:
    """Position reconciliation settings."""
    
    # Auto-square-off time (24-hour format as seconds from midnight)
    AUTO_SQUARE_OFF_HOUR: int = 15  # 15:20 IST default
    AUTO_SQUARE_OFF_MINUTE: int = 20
    
    # Auto-square-off check interval (seconds)
    CHECK_INTERVAL: float = 30.0


# =============================================================================
# Super Order Configuration
# =============================================================================

class SuperOrder:
    """Super order defaults."""
    
    # Default slice interval for TWAP (seconds)
    DEFAULT_SLICE_INTERVAL: int = 60
    # Default VWAP participation slice
    DEFAULT_VWAP_SLICE: int = 100


# =============================================================================
# WebSocket Connection Manager Constants
# =============================================================================

class WSManager:
    """WebSocket connection manager defaults."""
    
    # Default stale threshold for heartbeat (seconds)
    STALE_THRESHOLD: int = 20


# =============================================================================
# Helper Functions
# =============================================================================

def get_constant(env_var: str, default: str) -> str:
    """Get a constant value with environment variable override."""
    return os.environ.get(env_var, default)


def get_int_constant(env_var: str, default: int) -> int:
    """Get an integer constant with environment variable override."""
    return int(os.environ.get(env_var, str(default)))


def get_float_constant(env_var: str, default: float) -> float:
    """Get a float constant with environment variable override."""
    return float(os.environ.get(env_var, str(default)))


def get_bool_constant(env_var: str, default: bool) -> bool:
    """Get a boolean constant with environment variable override."""
    return os.environ.get(env_var, str(default)).lower() == "true"