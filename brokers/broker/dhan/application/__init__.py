"""
Dhan Application Layer - Main broker implementation and utilities.

This package provides the application layer for the Dhan broker implementation.
It contains the main DhanBroker class that implements IBrokerPort, configuration,
and data conversion utilities.

Public API:
    Config: DhanConfig
    Broker: DhanBroker
    Converter: DhanConverter
    Facade: DhanFacade (one-liner API)

Example:
    >>> from brokers.broker.dhan.application import DhanBroker, DhanConfig
    >>> 
    >>> # Create broker with factory method
    >>> broker = DhanBroker.create(
    ...     client_id="your_client_id",
    ...     access_token="your_access_token",
    ... )
    >>> 
    >>> # Or create from environment
    >>> config = DhanConfig.from_env()
    >>> broker = DhanBroker(config=config)
    >>> 
    >>> # Use as async context manager
    >>> async with broker:
    ...     quote = broker.get_quote(instrument)
    ...     async for tick in broker.stream_ticker([instrument]):
    ...         print(tick.price)
    >>> 
    >>> # Or use the simple facade for one-liners
    >>> from brokers.broker.dhan.application import DhanFacade
    >>> dhan = DhanFacade()
    >>> df = dhan.historical("NIFTY", "2024-01-01", "2024-01-31")
"""

# =============================================================================
# Configuration
# =============================================================================

from .config import DhanConfig

# =============================================================================
# Converter
# =============================================================================

from .converters import DhanConverter, to_segment

# =============================================================================
# Broker
# =============================================================================

from .broker import DhanBroker

# =============================================================================
# Facade (One-liner API)
# =============================================================================

from .facade import (
    DhanFacade,
    Trade,
    PnLReport,
)

# Exchange Resolver (for auto-detection)
from .exchange_resolver import (
    DhanExchangeResolver,
    ResolvedExchange,
)


# =============================================================================
# Public API - All exports
# =============================================================================

__all__ = [
    # Configuration
    "DhanConfig",
    
    # Converter
    "DhanConverter",
    "to_segment",
    
    # Broker
    "DhanBroker",
    
    # Facade
    "DhanFacade",
    "DhanExchangeResolver",
    "ResolvedExchange",
    "Trade",
    "PnLReport",
]
