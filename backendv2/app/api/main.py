"""FastAPI runtime control and event streaming API."""

from __future__ import annotations

from datetime import datetime
import logging
import os
from typing import List
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.api.routers import (
    ai_router,
    alerts_router,
    analysis_router,
    health_router,
    market_router,
    metrics_router,
    observability_router,
    scanner_router,
    rl_router,
    trading_router,
)
from app.api.websocket import gameloop_router
from app.application.commands.trading_commands import UpdateTick
from app.application.di.container import Container
from app.application.handlers.update_tick_handler import UpdateTickHandler
from app.core.metrics import MetricsRegistry
from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.core.event_store import EventStore
from app.core.feature_flags import FeatureFlags
from app.infrastructure.messaging.event_bus import EventBus
from app.infrastructure.serialization import OHLCDataDTO
from app.infrastructure.config import AppSettings, load_environment_config
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.runtime.orchestrator import RuntimeOrchestrator
from app.domain.risk.service import StartupReconciliation
from app.infrastructure.adapters.dhan_adapter import DhanAdapter
from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard, OptionScannerService
from app.domain.models.exchange_config import ExchangeConfig
from app.application.service.session_state_manager import SessionStateManager

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    # Initialize DI Container and register core services
    container = Container()
    container.register(MetricsRegistry, MetricsRegistry())
    container.register(CircuitBreaker, CircuitBreaker(CircuitBreakerConfig(
        failure_threshold=5,
        timeout_seconds=300.0,
        success_threshold=3
    )))
    container.register(EventStore, EventStore())
    container.register(FeatureFlags, FeatureFlags())
    application.state.container = container

    settings = AppSettings.from_yaml_file()
    runtime_config = load_environment_config(environment=getattr(settings, "environment", None))
    scanner = getattr(settings, "scanner", None)
    top_n = int(getattr(scanner, "top_n", 3))
    top_per_underlying = int(getattr(scanner, "top_per_underlying", 2))
    strikes_around_atm = int(getattr(scanner, "strikes_around_atm", 2))
    expiry_index = int(getattr(scanner, "expiry_index", 0))

    application.state.app_settings = settings
    application.state.storage = SQLiteStorageAdapter(settings.db_path)
    application.state.orchestrator = RuntimeOrchestrator(storage=application.state.storage)
    application.state.session_service = SessionStateManager(storage=application.state.storage)
    application.state.connected_clients = connected_clients

    broker_cfg = runtime_config.get("broker", {}) if isinstance(runtime_config, dict) else {}
    client_id = os.getenv("DHAN_CLIENT_ID") or str(broker_cfg.get("client_id", ""))
    access_token = os.getenv("DHAN_ACCESS_TOKEN") or str(broker_cfg.get("access_token", ""))
    default_exchange_name = os.getenv("DEFAULT_EXCHANGE", "NSE").upper()
    exchanges = runtime_config.get("exchanges", {}) if isinstance(runtime_config, dict) else {}
    selected_exchange = None
    for ex_name, ex_data in exchanges.items():
        if not isinstance(ex_data, dict) or not ex_data.get("enabled", True):
            continue
        selected_exchange = str(ex_name).upper()
        break
    if selected_exchange is None:
        selected_exchange = default_exchange_name

    ex_data = exchanges.get(selected_exchange, {}) if isinstance(exchanges, dict) else {}
    symbols_cfg = ex_data.get("symbols", {}) if isinstance(ex_data, dict) else {}
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

    market_data = DhanAdapter(
        symbols=configured_symbols,
        exchange="NFO" if selected_exchange == "NSE" else "MCX",
        client_id=client_id,
        access_token=access_token,
        testnet=bool(broker_cfg.get("testnet", True)),
    )
    application.state.market_data_adapter = market_data
    application.state.exchange_config = exchange_config
    application.state.active_symbols = list(configured_symbols)
    application.state.contract_guard = ContractSwitchGuard()
    application.state.scanner_status = {
        "last_scan_time": None,
        "parameters": {
            "n": top_n,
            "top_per_underlying": top_per_underlying,
            "strikes_around_atm": strikes_around_atm,
            "expiry_index": expiry_index,
            "exchange": selected_exchange,
            "underlyings": list(configured_symbols),
        },
        "result_count": 0,
    }
    try:
        scanner_service = OptionScannerService(market_data, default_underlyings=list(configured_symbols))
        now = time.time()
        async_scan_result = await asyncio.get_running_loop().run_in_executor(
            None,
            scanner_service.scan_top_n,
            top_n,
            configured_symbols,
            None,
            top_per_underlying,
            ("NFO" if selected_exchange == "NSE" else "MCX"),
            expiry_index,
            strikes_around_atm,
        )
        symbols = [r.symbol for r in async_scan_result[:top_n]]
        if symbols:
            application.state.active_symbols = symbols
            if async_scan_result:
                first = async_scan_result[0]
                application.state.contract_guard.record_switch(first.symbol, first.score, now)
            application.state.scanner_status["result_count"] = len(symbols)
            application.state.scanner_status["last_scan_time"] = datetime.utcnow().isoformat()
    except Exception as exc:
        logger.warning(
            "scanner startup failed; keeping configured symbols from config. error=%s",
            exc,
            exc_info=True,
        )
        application.state.scanner_status["last_scan_time"] = datetime.utcnow().isoformat()
        application.state.scanner_status["error"] = str(exc)

    try:
        startup_reconciliation = StartupReconciliation(
            broker_adapter=market_data,
            storage=application.state.storage,
        )
        application.state.startup_reconciliation = startup_reconciliation.reconcile(
            portfolio=None,
        )
        logger.info(
            "Startup reconciliation complete: %s",
            application.state.startup_reconciliation,
        )
    except Exception as exc:
        application.state.startup_reconciliation = None
        logger.warning("Startup reconciliation failed: %s", exc, exc_info=True)

    yield

    orchestrator = getattr(application.state, "orchestrator", None)
    if isinstance(orchestrator, RuntimeOrchestrator):
        orchestrator.teardown_all()

    storage = getattr(application.state, "storage", None)
    if hasattr(storage, "flush"):
        storage.flush()
    if hasattr(storage, "close"):
        storage.close()

app = FastAPI(
    title="GlassyTrade AI BackendV2 API",
    description="Runtime control API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(lambda origins: origins if origins else ["http://localhost:5173", "http://localhost:3000"])(
        [item.strip() for item in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if item.strip()],
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

event_bus = EventBus()
connected_clients: List[asyncio.Queue] = []
app.state.connected_clients = connected_clients

app.include_router(metrics_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(trading_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(gameloop_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(observability_router, prefix="/api")
app.include_router(rl_router, prefix="/api")
app.include_router(scanner_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "GlassyTrade AI BackendV2", "version": "2.0.0"}


@app.get("/api/stream")
async def stream_events(request: Request):
    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        connected_clients.append(queue)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {"event": "update", "data": json.dumps(event_data)}
                except asyncio.TimeoutError:
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"timestamp": datetime.utcnow().isoformat()}),
                    }
        finally:
            if queue in connected_clients:
                connected_clients.remove(queue)

    return EventSourceResponse(event_generator())


@app.post("/api/tick")
async def process_tick(tick: OHLCDataDTO):
    if not tick.symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    cmd = UpdateTick(
        symbol=tick.symbol,
        timestamp=float(tick.timestamp or datetime.utcnow().timestamp()),
        price=tick.close,
        volume=tick.volume,
    )
    handler = UpdateTickHandler(event_bus=event_bus)
    handler.handle(cmd)

    event_data = {
        "type": "tick",
        "symbol": cmd.symbol,
        "price": cmd.price,
        "timestamp": datetime.utcnow().isoformat(),
    }
    for queue in connected_clients:
        await queue.put(event_data)

    return {"status": "processed", "symbol": cmd.symbol}