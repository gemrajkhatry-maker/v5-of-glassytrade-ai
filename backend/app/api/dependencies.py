"""API dependency injection — explicit constructor injection (replaces ServiceGraph).

This module provides FastAPI dependencies using module-level singletons
created at startup, eliminating the ServiceGraph service locator anti-pattern.

Active-symbols ownership: this module owns the canonical snapshot
(``_active_symbols``). ``main.py`` is the SOLE writer via its
``_set_active_symbols()`` helper (lifespan scan wins; factory fallback only
seeds when the scan is absent). Readers use ``get_active_symbols()`` (a
``list`` copy — the stored snapshot is a tuple) or ``coordinator.symbols()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

if TYPE_CHECKING:
    from app.config import Configuration
    from quant.contracts.ports.broker import IBroker
    from quant.contracts.ports.market_data import IMarketData
    from quant.contracts.ports.storage import IStorage

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
    _active_symbols = tuple(active_symbols or ())
    _coordinator = coordinator


def set_coordinator(coordinator) -> None:
    """Sync the coordinator singleton after lifespan boot (lifespan runs after factory init)."""
    global _coordinator
    _coordinator = coordinator


def set_active_symbols(symbols) -> None:
    """Sync the active-symbols singleton (called only by main._set_active_symbols)."""
    global _active_symbols
    _active_symbols = tuple(symbols or ())


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
ConfigDep = Annotated["Configuration", Depends(get_configuration)]


def get_trade_journal():
    """Dependency: Trade journal service."""
    from app.application.services.trade_journal import TradeJournal
    return TradeJournal()

