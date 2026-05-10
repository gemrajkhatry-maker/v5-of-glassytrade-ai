"""Application lifespan — replaces the monolithic api/main.py bootstrap."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.application.service.session_state_manager import SessionStateManager
from app.bootstrap.container import bootstrap_container
from app.bootstrap.infrastructure import (
    bootstrap_market_data,
    bootstrap_storage,
    build_exchange_config,
    load_settings,
    resolve_exchange,
)
from app.bootstrap.scanner import (
    build_scanner_status,
    run_initial_scan,
    update_scanner_status,
)
from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard, OptionScannerService
from app.domain.risk.service import StartupReconciliation
from app.infrastructure.messaging.event_bus import EventBus
from app.runtime.orchestrator import RuntimeOrchestrator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def create_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — bootstraps all layers and yields to serve requests."""
    # ── DI Container ──────────────────────────────────────────────────────
    container = bootstrap_container()
    app.state.container = container

    # ── Settings & Config ─────────────────────────────────────────────────
    settings, runtime_config = load_settings()
    scanner_cfg = getattr(settings, "scanner", None)
    top_n = int(getattr(scanner_cfg, "top_n", 3))
    top_per_underlying = int(getattr(scanner_cfg, "top_per_underlying", 2))
    strikes_around_atm = int(getattr(scanner_cfg, "strikes_around_atm", 2))
    expiry_index = int(getattr(scanner_cfg, "expiry_index", 0))

    app.state.app_settings = settings

    # ── Storage & Orchestration ───────────────────────────────────────────
    storage = bootstrap_storage(settings)
    app.state.storage = storage
    app.state.orchestrator = RuntimeOrchestrator(storage=storage)
    app.state.session_service = SessionStateManager(storage=storage)

    # ── Exchange Resolution ───────────────────────────────────────────────
    strategy_mode = os.getenv("GLASSYTRADE_STRATEGY", "").lower()
    selected_exchange, ex_data = resolve_exchange(runtime_config, strategy_mode)
    symbols_cfg = ex_data.get("symbols", {})
    exchange_config, configured_symbols = build_exchange_config(
        selected_exchange, ex_data, symbols_cfg
    )
    app.state.exchange_config = exchange_config
    app.state.active_symbols = list(configured_symbols)

    # ── Broker / Market Data Adapter ──────────────────────────────────────
    broker_cfg = runtime_config.get("broker", {})
    client_id = os.getenv("DHAN_CLIENT_ID") or str(broker_cfg.get("client_id", ""))
    access_token = os.getenv("DHAN_ACCESS_TOKEN") or str(broker_cfg.get("access_token", ""))
    testnet = bool(broker_cfg.get("testnet", True))

    market_data = bootstrap_market_data(
        configured_symbols, selected_exchange, client_id, access_token, testnet
    )
    app.state.market_data_adapter = market_data

    # ── Scanner Bootstrap ─────────────────────────────────────────────────
    scanner_status = build_scanner_status(
        top_n, top_per_underlying, strikes_around_atm,
        expiry_index, selected_exchange, configured_symbols,
    )
    app.state.scanner_status = scanner_status

    contract_guard = ContractSwitchGuard()
    app.state.contract_guard = contract_guard

    try:
        scanner_service = OptionScannerService(
            market_data, default_underlyings=list(configured_symbols)
        )
        symbols, decision_dict = await run_initial_scan(
            scanner_service,
            configured_symbols,
            top_n,
            top_per_underlying,
            "NFO" if selected_exchange == "NSE" else "MCX",
            expiry_index,
            strikes_around_atm,
            contract_guard,
        )
        if symbols and (decision_dict is None or decision_dict.get("accepted") or decision_dict.get("reason") == "same_contract"):
            app.state.active_symbols = symbols
        update_scanner_status(scanner_status, app.state.active_symbols, decision_dict)
    except Exception as exc:
        logger.warning(
            "scanner startup failed; keeping configured symbols. error=%s",
            exc,
            exc_info=True,
        )
        update_scanner_status(scanner_status, [], error=exc)

    # ── Startup Reconciliation ────────────────────────────────────────────
    try:
        startup_reconciliation = StartupReconciliation(
            broker_adapter=market_data,
            storage=storage,
        )
        app.state.startup_reconciliation = startup_reconciliation.reconcile(portfolio=None)
        logger.info("Startup reconciliation complete: %s", app.state.startup_reconciliation)
    except Exception as exc:
        app.state.startup_reconciliation = None
        logger.warning("Startup reconciliation failed: %s", exc, exc_info=True)

    yield  # ── Application serves requests ────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────
    orchestrator = getattr(app.state, "orchestrator", None)
    if isinstance(orchestrator, RuntimeOrchestrator):
        orchestrator.teardown_all()

    if hasattr(storage, "flush"):
        storage.flush()
    if hasattr(storage, "close"):
        storage.close()
