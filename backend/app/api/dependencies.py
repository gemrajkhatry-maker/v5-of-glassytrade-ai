"""API dependency injection — explicit constructor injection (replaces ServiceGraph).

This module provides FastAPI dependencies using module-level singletons
created at startup, eliminating the ServiceGraph service locator anti-pattern.
"""

from __future__ import annotations

from fastapi import Depends, Request
from typing import Annotated

# Module-level singletons (created by init_singletons() in main.py)
_broker = None
_storage = None
_market_data = None
_configuration = None
_active_symbols = []
_coordinator = None


def init_singletons(
    broker,
    storage,
    market_data,
    configuration,
    active_symbols,
    coordinator=None,
) -> None:
    """Initialize module-level singletons at startup (called from main.py)."""
    global _broker, _storage
    global _market_data, _configuration, _active_symbols
    global _coordinator

    _broker = broker
    _storage = storage
    _market_data = market_data
    _configuration = configuration
    _active_symbols = active_symbols
    _coordinator = coordinator


def set_coordinator(coordinator) -> None:
    """Sync the coordinator singleton after lifespan boot (lifespan runs after factory init)."""
    global _coordinator
    _coordinator = coordinator


# FastAPI dependency functions
def get_broker() -> "IBroker":
    """Dependency: Broker adapter."""
    return _broker


def get_storage() -> "IStorage":
    """Dependency: Storage adapter."""
    return _storage


def get_market_data() -> "IMarketData":
    """Dependency: Market data adapter."""
    return _market_data


def get_configuration() -> "Configuration":
    """Dependency: Application configuration."""
    return _configuration


def get_active_symbols() -> list:
    """Dependency: Active symbols."""
    return list(_active_symbols)


def get_coordinator():
    """Dependency: QuantCoordinator view (ICoordinatorView surface)."""
    return _coordinator


# Annotated types for FastAPI
BrokerDep = Annotated["IBroker", Depends(get_broker)]
StorageDep = Annotated["IStorage", Depends(get_storage)]
MarketDataDep = Annotated["IMarketData", Depends(get_market_data)]
ConfigDep = Annotated["Configuration", Depends(get_configuration)]
ActiveSymbolsDep = Annotated[list, Depends(get_active_symbols)]

def get_trade_journal():
    """Dependency: Trade journal service."""
    from app.application.services.trade_journal import TradeJournal
    return TradeJournal()

