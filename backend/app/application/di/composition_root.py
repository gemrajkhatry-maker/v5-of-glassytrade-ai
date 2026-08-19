"""Composition Root — builds the dependency graph.

This module is the ONLY place in the application where concrete
implementations are imported. Everything else depends on ports.

Usage:
    container = compose_container(config)
    session = container.resolve(TradingSessionService)
"""

from __future__ import annotations

import logging

from app.config_models import SystemConfig as Configuration
from app.config import settings as _settings

from app.shared.mode import is_live_mode

logger = logging.getLogger(__name__)

from app.application.di.container import DIContainer


def compose_container(config: "Configuration") -> DIContainer:
    """Build the complete dependency graph.

    Args:
        config: Application configuration.

    Returns:
        A fully wired DIContainer ready for resolution.
    """
    container = DIContainer()

    # --- Configuration ---
    container.register_singleton(
        Configuration,
        lambda c: config,
    )

    # --- Infrastructure Adapters ---
    container.register_singleton(
        _market_data_port(),
        lambda c: _create_market_data_adapter(c, config),
    )

    container.register_singleton(
        _broker_port(),
        lambda c: _create_broker_adapter(c, config),
    )

    container.register_singleton(
        _storage_port(),
        lambda c: _create_storage_adapter(c, config),
    )

    container.register_singleton(
        _quant_coordinator(),
        lambda c: _create_quant_coordinator(c, config),
    )

    return container


# ---------------------------------------------------------------------------
# Port type getters (lazy to avoid circular imports)
# ---------------------------------------------------------------------------

def _market_data_port():
    from quant.contracts.ports.market_data import IMarketData
    return IMarketData


def _broker_port():
    from quant.contracts.ports.broker import IBroker
    return IBroker


def _storage_port():
    from quant.contracts.ports.storage import IStorage
    return IStorage


def _quant_coordinator():
    from quant.multi_engine import QuantCoordinator
    return QuantCoordinator


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def _create_market_data_adapter(container: DIContainer, config: "Configuration"):
    from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
    return DhanMarketDataAdapter(config)


def _create_broker_adapter(container: DIContainer, config: "Configuration"):
    live_mode = is_live_mode()
    if live_mode:
        from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
        return DhanBrokerAdapter(config)
    from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
    return PaperBrokerAdapter()


def _create_storage_adapter(container: DIContainer, config: "Configuration"):
    from app.infrastructure.storage.database import SQLiteStorageAdapter
    db_path = getattr(config, "db_path", "glassytrade.db")
    return SQLiteStorageAdapter(db_path)


def _create_quant_coordinator(container: DIContainer, config: "Configuration"):
    """Build the QuantCoordinator — the deterministic decision brain for the
    WS viewer + REST shell. Reuses the same market-data / broker adapters
    registered for the app; the coordinator only starts its engines when
    main.py gates it via GREENFIELD_ENGINE=1."""
    from quant.multi_engine import QuantCoordinator
    from quant.contracts.ports.market_data import IMarketData
    from quant.contracts.ports.broker import IBroker

    market_data = container.resolve(IMarketData)
    broker = container.resolve(IBroker)

    candle_minutes = int(getattr(config, "candle_timeframe_minutes", 5) or 5)
    scanner_cfg = getattr(config, "scanner", None)
    include_futures = getattr(scanner_cfg, "include_futures", True) if scanner_cfg else True

    coord_config = {
        "underlyings": list(_settings.SCANNER_UNDERLYINGS or []),
        "n": int(_settings.SCANNER_TOP_N or 8),
        "exchange": _settings.DEFAULT_EXCHANGE or "NSE",
        "expiry_index": int(_settings.SCANNER_EXPIRY_INDEX or 0),
        "strikes_around_atm": int(_settings.STRIKES_AROUND_ATM or 2),
        "interval_seconds": candle_minutes * 60,
        "include_futures": include_futures,
        "underlying_priority": _settings.SCANNER_UNDERLYING_PRIORITY,
    }
    logger.info(
        "QuantCoordinator config: underlyings=%s n=%d exchange=%s expiry_index=%d "
        "strikes_around_atm=%d interval_seconds=%d priority=%s include_futures=%s",
        coord_config["underlyings"],
        coord_config["n"],
        coord_config["exchange"],
        coord_config["expiry_index"],
        coord_config["strikes_around_atm"],
        coord_config["interval_seconds"],
        coord_config["underlying_priority"],
        coord_config["include_futures"],
    )
    return QuantCoordinator(
        market_data=market_data,
        broker=broker,
        config=coord_config,
    )


