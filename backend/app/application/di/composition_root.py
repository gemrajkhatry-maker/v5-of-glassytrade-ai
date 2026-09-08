"""Composition Root — builds the dependency graph.

This module is the ONLY place in the application where concrete
implementations are imported. Everything else depends on ports.

Usage:
    container = compose_container(config)
    coordinator = container.resolve(QuantCoordinator)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

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
        from quant.contracts.ports.storage import IStorage
        # C4: wire durable order storage so live order state transitions are
        # persisted for crash recovery. Best-effort — a missing storage adapter
        # must never block live execution.
        try:
            storage = container.resolve(IStorage)
        except Exception:
            logger.warning("No storage adapter available for durable order persistence")
            storage = None
        return DhanBrokerAdapter(config, storage=storage)
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
    from quant.contracts.ports.storage import IStorage

    market_data = container.resolve(IMarketData)
    broker = container.resolve(IBroker)
    storage = container.resolve(IStorage)

    candle_minutes = int(getattr(config, "candle_timeframe_minutes", 5) or 5)
    scanner_cfg = getattr(config, "scanner", None)
    include_futures = getattr(scanner_cfg, "include_futures", True) if scanner_cfg else True

    coord_config = {
        "journal_dir": str(Path(__file__).resolve().parents[3] / "journals"),
        "underlyings": list(_settings.SCANNER_UNDERLYINGS or []),
        "n": int(_settings.SCANNER_TOP_N or 8),
        "exchange": _settings.DEFAULT_EXCHANGE or "NSE",
        "strategy_name": getattr(_settings, "GLASSYTRADE_STRATEGY", None) or "mcx_options",
        "execution_model": getattr(config, "execution_model", "independent"),
        "expiry_index": int(_settings.SCANNER_EXPIRY_INDEX or 0),
        "strikes_around_atm": int(_settings.STRIKES_AROUND_ATM or 2),
        "interval_seconds": candle_minutes * 60,
        "include_futures": include_futures,
        "underlying_priority": _settings.SCANNER_UNDERLYING_PRIORITY,
        "live_oms_enabled": is_live_mode(),
        # Paper execution consumes the same validated per-root cost profile
        # that the config loader uses for the selected exchange. Keeping this
        # mapping at composition time prevents the quant runtime from reading
        # YAML or inventing brokerage/slippage defaults.
        "cost_profiles": _coordinator_cost_profiles(config),
        "advisor_enabled": (
            os.getenv("LLM_ADVISOR_ENABLED", "false").strip().lower() in ("true", "1", "yes")
            or os.getenv("TIMESFM_ADVISOR_ENABLED", "false").strip().lower() in ("true", "1", "yes")
        ),
        # C2: the configured per-trade risk must reach the engines' SessionRisk.
        # NO silent fallback: the effective value is whatever the loader + live
        # validator settled on (config_models), and boot fails if it is absent.
        # The old getattr(..., 0.005/0.02/3/6) literals here were a THIRD risk
        # authority that could drift from the validated YAML value.
        **_coordinator_risk_config(config),
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
        storage=storage,
    )


def _require_risk_value(config: "Configuration", name: str):
    """Return a required risk field or fail boot — never default silently.

    The typed RiskConfig always carries these fields today, so this guard only
    fires if a future refactor removes/renames a field or makes it optional.
    Failing here (instead of a getattr default) keeps the YAML -> validator ->
    composition_root chain the ONE risk authority: a missing live risk value
    must stop startup, not quietly trade at an unvalidated fallback.
    """
    risk = getattr(config, "risk", None)
    value = getattr(risk, name, None) if risk is not None else None
    if value is None:
        raise ValueError(
            "Refusing to start engines: required risk setting "
            f"'config.risk.{name}' is missing/None. Declare it in "
            "backend/config (base.yaml + environments/live.yaml) — there is "
            "no silent risk default."
        )
    return value


def _coordinator_cost_profiles(config: "Configuration") -> dict[str, dict]:
    """Expose validated per-root cost profiles to the quant coordinator."""
    profiles: dict[str, dict] = {}
    for exchange in getattr(config, "exchanges", {}).values():
        for root, symbol_config in getattr(exchange, "symbols", {}).items():
            profile = getattr(symbol_config, "cost_profile", None)
            if profile is None:
                raise ValueError(
                    f"Refusing to start: cost profile missing for configured root {root!r}"
                )
            profiles[str(root).upper()] = {
                "fill_mode": str(getattr(profile, "fill_mode", "bid_ask")),
                "slippage_bps": float(profile.slippage_bps),
                "stt_pct": float(profile.stt_pct),
                "exchange_fee_pct": float(profile.exchange_fee_pct),
                "brokerage_per_order": float(profile.brokerage_per_order),
                "gst_on_brokerage_pct": float(profile.gst_on_brokerage_pct),
                "sebi_charges_pct": float(profile.sebi_charges_pct),
            }
    return profiles


def _coordinator_risk_config(config: "Configuration") -> dict:
    """The risk values the coordinator must pass to every engine's SessionRisk.

    These are the exact values the loader + validator settled on — the values
    are read, never re-defaulted. A missing field aborts coordinator startup.
    """
    return {
        "max_trades_per_session": int(_require_risk_value(config, "max_trades_per_session")),
        "risk_per_trade_pct": float(_require_risk_value(config, "risk_per_trade_pct")),
        "capital_deployment_pct": float(config.paper.capital_deployment_pct),
        "max_daily_loss_pct": float(_require_risk_value(config, "max_daily_loss_pct")),
        "max_consecutive_losses": int(_require_risk_value(config, "max_consecutive_losses")),
    }


