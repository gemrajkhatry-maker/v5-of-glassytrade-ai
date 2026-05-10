"""Infrastructure bootstrap — settings, storage, adapters, exchange config."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.infrastructure.adapters.dhan_adapter import DhanAdapter
from app.infrastructure.config import AppSettings, load_environment_config
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.domain.models.exchange_config import ExchangeConfig

logger = logging.getLogger(__name__)


def load_settings() -> tuple[AppSettings, dict[str, Any]]:
    """Load application settings and runtime configuration.

    Returns (app_settings, runtime_config_dict).
    """
    settings = AppSettings.from_yaml_file()
    runtime_config = load_environment_config(environment=getattr(settings, "environment", None))
    if not isinstance(runtime_config, dict):
        runtime_config = {}
    return settings, runtime_config


def resolve_exchange(
    runtime_config: dict[str, Any],
    strategy_mode: str,
) -> tuple[str, dict[str, Any]]:
    """Determine which exchange to use based on strategy and config.

    Returns (exchange_name, exchange_data_dict).
    """
    default_exchange_name = os.getenv("DEFAULT_EXCHANGE", "NSE").upper()

    if "mcx" in strategy_mode:
        default_exchange_name = "MCX"
        logger.info("GLASSYTRADE_STRATEGY=%s, forcing MCX exchange", strategy_mode)

    exchanges = runtime_config.get("exchanges", {})
    selected_exchange = None

    for ex_name, ex_data in exchanges.items():
        if not isinstance(ex_data, dict) or not ex_data.get("enabled", True):
            continue
        if "mcx" in strategy_mode and str(ex_name).upper() == "MCX":
            selected_exchange = "MCX"
            break
        if "nse" in strategy_mode and str(ex_name).upper() == "NSE":
            selected_exchange = "NSE"
            break
        if selected_exchange is None:
            selected_exchange = str(ex_name).upper()

    if selected_exchange is None:
        selected_exchange = default_exchange_name

    ex_data = exchanges.get(selected_exchange, {})
    return selected_exchange, ex_data if isinstance(ex_data, dict) else {}


def build_exchange_config(
    selected_exchange: str,
    ex_data: dict[str, Any],
    symbols_cfg: dict[str, Any],
) -> tuple[ExchangeConfig, list[str]]:
    """Build ExchangeConfig and list of configured symbols.

    Returns (exchange_config, configured_symbols).
    """
    configured_symbols = [
        symbol_name
        for symbol_name, symbol_cfg in symbols_cfg.items()
        if not isinstance(symbol_cfg, dict) or symbol_cfg.get("enabled", True)
    ]

    try:
        exchange_config = ExchangeConfig.from_dict(selected_exchange, ex_data)
        configured_symbols = list(exchange_config.scanner_underlyings) or configured_symbols
    except Exception:
        exchange_config = ExchangeConfig.for_exchange(selected_exchange)

    return exchange_config, configured_symbols


def bootstrap_storage(settings: AppSettings) -> SQLiteStorageAdapter:
    """Create and return the SQLite storage adapter."""
    return SQLiteStorageAdapter(settings.db_path)


def bootstrap_market_data(
    configured_symbols: list[str],
    selected_exchange: str,
    client_id: str,
    access_token: str,
    testnet: bool,
) -> DhanAdapter:
    """Create the Dhan market data adapter."""
    return DhanAdapter(
        symbols=configured_symbols,
        exchange="NFO" if selected_exchange == "NSE" else "MCX",
        client_id=client_id,
        access_token=access_token,
        testnet=testnet,
    )
