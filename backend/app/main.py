#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Main application entry point.

This module sets up the dependency injection graph and starts the FastAPI application.
"""

import faulthandler
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import MappingProxyType
from typing import AsyncGenerator

# Load .env BEFORE any other imports that read os.getenv()
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Enable faulthandler to print Python traceback on segfault
faulthandler.enable()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    health_router,
    market_router,
    trading_router,
    journal_router,
    metrics_router,
    testing_router,
)
from app.api.routers.observability import router as observability_router
from app.api.routers.alerts import router as alerts_router
from app.api.routers.analysis import router as analysis_router
from app.api.websocket.gameloop import router as gameloop_router
from app.api.dependencies import init_singletons
from app.core.correlation import CorrelationIdMiddleware
from app.core.logging import setup_logging, get_logger
from app.core.startup_telemetry import (
    begin_phase,
    end_phase,
    record_startup_reconciliation,
    mark_startup_failed,
    mark_startup_finished,
    mark_startup_started,
)
from app.core.async_boundary import ensure_sync_adapter_result
from app.config import settings as _settings
from quant.contracts.ports.broker import IBroker
from quant.contracts.ports.storage import IStorage
from quant.contracts.ports.market_data import IMarketData
from app.domain.ops.startup_reconciliation import StartupReconciliation
from app.shared.mode import resolve_runtime_mode


def _build_startup_contracts(
    *,
    broker,
    storage,
    active_symbols: list[str],
    coordinator=None,
    engine_start_failed: bool = False,
    reconciliation_result=None,
    reconciliation_executed: bool | None = None,
) -> dict[str, str]:
    """Minimal startup-readiness payload for the health router.

    The QuantCoordinator is the decision brain, so this thin payload
    reports transport-shell readiness only.
    """
    checks: dict[str, str] = {}
    checks["active_symbols"] = (
        f"ok({len(active_symbols)})"
        if active_symbols
        else "error: no active symbols selected"
    )
    from app.config import settings

    checks["scanner_settings"] = (
        "ok"
        if settings.SCANNER_TOP_N > 0 and settings.DEFAULT_EXCHANGE
        else "error: invalid scanner configuration"
    )
    broker_ok = callable(getattr(broker, "execute_order", None)) and callable(
        getattr(broker, "cancel_order", None)
    )
    checks["broker_runtime"] = "ok" if broker_ok else "error: broker runtime contract missing"
    storage_ok = all(
        callable(getattr(storage, attr, None))
        for attr in ("save_open_position", "delete_open_position", "save_trade", "kv_set")
    )
    checks["storage_runtime"] = "ok" if storage_ok else "error: storage runtime contract missing"

    # ponytail: real probes for strategy_runtime and position_close_contract
    if engine_start_failed:
        checks["strategy_runtime"] = "error: strategy runtime failed to start"
    elif coordinator is None and not broker_ok:
        checks["strategy_runtime"] = "error: strategy runtime coordinator missing"
    else:
        checks["strategy_runtime"] = "ok"

    broker_close_ok = callable(getattr(broker, "close_position", None)) or (
        callable(getattr(broker, "execute_order", None)) and callable(getattr(broker, "cancel_order", None))
    )
    coord_close_ok = (
        coordinator is None
        or callable(getattr(coordinator, "emergency_halt", None))
        or callable(getattr(coordinator, "force_close_position", None))
    )
    checks["position_close_contract"] = (
        "ok" if (broker_close_ok and coord_close_ok) else "error: position close contract missing on broker or coordinator"
    )
    if reconciliation_executed is None:
        reconciliation_executed = reconciliation_result is not None
    checks["reconciliation"] = (
        "ok" if reconciliation_executed else "error: reconciliation not executed"
    )
    if reconciliation_result is not None:
        checks["reconciliation_summary"] = (
            f"db={reconciliation_result.db_positions} "
            f"broker={reconciliation_result.broker_positions} "
            f"restored={reconciliation_result.restored} "
            f"stale={reconciliation_result.stale_removed} "
            f"orphaned={reconciliation_result.orphaned_registered}"
        )
        checks["reconciliation_discrepancies"] = str(
            len(reconciliation_result.discrepancies)
        )
    else:
        checks["reconciliation_summary"] = "not_run"
        checks["reconciliation_discrepancies"] = "n/a"

    critical_keys = {
        "active_symbols",
        "scanner_settings",
        "broker_runtime",
        "storage_runtime",
        "strategy_runtime",
        "position_close_contract",
        "reconciliation",
    }
    status = "ok" if all(checks.get(k, "").startswith("ok") for k in critical_keys) else "degraded"
    payload = json.dumps(checks, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    contract_id = f"startup-contract:{hashlib.sha256(payload.encode()).hexdigest()[:12]}"
    return {**checks, "contract_id": contract_id, "status": status}

# Configure structured logging
setup_logging()
logger = get_logger(__name__)


class WebSocketLogMiddleware:
    """Log WebSocket connection attempts for debugging."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/api/trading/ws/gameloop":
            logger.info(
                "WebSocket request: method=%s, path=%s",
                scope.get("method", ""),
                scope.get("path", ""),
            )
        await self.app(scope, receive, send)


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    mark_startup_started()
    begin_phase("application_init")
    import os  # local: startup-only env read, keeps module import surface unchanged
    runtime_mode = resolve_runtime_mode()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        """Application lifespan: startup and shutdown."""
        # Startup
        logger.info("Starting GlassyTrade AI application...")
        begin_phase("lifespan_startup")

        # Get service container from app state
        container = app.state.container

        # Run option scanner to select MCX/NSE contracts — unless a valid
        # persisted selection for today exists. Reusing the same contracts on a
        # restart keeps the strikes stable and preserves per-symbol decision
        # history in the UI; the scanner only re-runs on a new trading day or
        # via an explicit /api/scanner/rescan.
        logger.info("Running option scanner to select contracts...")
        begin_phase("option_scanner")
        try:
            from quant.multi_engine import load_persisted_contracts

            # Reuse today's persisted selection only when it was selected for
            # the same exchange as the active strategy (e.g. NSE picks must not
            # leak into an MCX session after a mid-day strategy switch).
            persisted = load_persisted_contracts(
                exchange=_settings.DEFAULT_EXCHANGE
            )
            selected_symbols = list(persisted or [])

            if persisted:
                logger.info(
                    "Reusing persisted contracts (same trading day): %s", persisted
                )
            else:
                from quant.amt.session.scanner import OptionScannerService
                from quant.amt.session.scanner_config import ScannerConfig
                from app.config import settings
                import concurrent.futures

                scanner = OptionScannerService(container.resolve(IMarketData))
                scan_cfg = ScannerConfig.from_settings(settings)

                # Run scanner in thread pool (it's synchronous)
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    results = pool.submit(
                        scanner.scan_top_n,
                        **scan_cfg.to_scan_kwargs(
                            exchange=settings.DEFAULT_EXCHANGE
                        ),
                    ).result(timeout=120)

                if results:
                    # Filter to valid contracts with LTP > 0
                    final = [r for r in results if r.ltp > 0] or results
                    selected_symbols = [
                        r.symbol for r in final[:scan_cfg.top_n]
                    ]

            if selected_symbols:
                app.state.active_symbols = selected_symbols
                logger.info(
                    "Option scanner selected %d contracts: %s",
                    len(selected_symbols),
                    selected_symbols
                )
            else:
                logger.warning(
                    "No contracts selected — using default underlyings: %s",
                    app.state.active_symbols
                )
            end_phase("option_scanner", "ok")
        except Exception as e:
            logger.error("Option scanner failed: %s — using default underlyings", e, exc_info=True)
            end_phase("option_scanner", "failed", str(e))
            mark_startup_failed("config", str(e))
            if runtime_mode == "live":
                # In live mode, falling back to configured underlyings can
                # spawn instruments that were never validated by the scanner.
                # Refuse startup instead of silently changing the traded book.
                raise RuntimeError(
                    f"Live startup refused: option scanner failed: {e}"
                ) from e

        # Boot the QuantCoordinator — the single decision brain.
        startup_ok = True
        try:
            begin_phase("trading_engine")
            from quant.multi_engine import QuantCoordinator

            coordinator = container.resolve(QuantCoordinator)
            app.state.coordinator = coordinator
            coordinator.start()
            end_phase("trading_engine", "ok")
            logger.info("QuantCoordinator started — serving %s", coordinator.symbols())
        except Exception:
            logger.error("QuantCoordinator failed to start!", exc_info=True)
            app.state.engine_start_failed = True
            startup_ok = False
            end_phase("trading_engine", "failed", "coordinator.start() raised exception")
            mark_startup_failed("engine")

        end_phase("lifespan_startup", "ok" if startup_ok else "warn")
        if startup_ok and not getattr(app.state, "engine_start_failed", False):
            mark_startup_finished()

        logger.info("Application started successfully")

        import signal as _signal

        _prev_sigterm = _signal.getsignal(_signal.SIGTERM)

        def _emergency_flatten(signum, frame):
            import logging
            _log = logging.getLogger('emergency.shutdown')
            _log.critical('SIGTERM received — initiating emergency risk halt', extra={'event': 'EMERGENCY_SHUTDOWN'})
            try:
                # Audit D-RISK-03: the old handler set eng._risk_halted — an
                # attribute QuantEngine never had — so this was a silent no-op.
                # Route through the coordinator into each engine's SessionRisk,
                # which is what the decision loop actually consults.
                if hasattr(app.state, 'coordinator'):
                    coord = app.state.coordinator
                    if hasattr(coord, 'emergency_halt'):
                        halted = coord.emergency_halt("SIGTERM shutdown", force_close=True)
                        _log.critical(
                            'Emergency halt applied to %d engine(s)', halted,
                            extra={'event': 'EMERGENCY_SHUTDOWN_APPLIED'},
                        )
            except Exception as exc:
                _log.error('Emergency flatten error: %s', exc)
            # Chain to the previously installed handler (uvicorn's): without
            # this the server ignores SIGTERM forever, operators escalate to
            # SIGKILL, and lifespan teardown (coordinator.stop + storage
            # flush) never runs.
            if callable(_prev_sigterm):
                _prev_sigterm(signum, frame)

        _signal.signal(_signal.SIGTERM, _emergency_flatten)

        yield  # Server is running

        # Shutdown
        logger.info("Shutting down GlassyTrade AI application...")

        # Stop greenfield coordinator
        if hasattr(app.state, "coordinator"):
            try:
                app.state.coordinator.stop()
                logger.info("QuantCoordinator stopped")
            except Exception:
                logger.error(
                    "QuantCoordinator stop failed — resources may not be cleaned up",
                    exc_info=True,
                )

        # Persist pending in-memory data and release storage resources
        try:
            storage = getattr(app.state, "storage", None)
            if hasattr(storage, "flush"):
                ensure_sync_adapter_result("storage.flush", storage.flush)
                logger.info("Storage flushed")
            if hasattr(storage, "close"):
                ensure_sync_adapter_result("storage.close", storage.close)
                logger.info("Storage closed")
        except Exception:
            logger.debug("Storage teardown failed — non-critical", exc_info=True)

        logger.info("Shutdown complete")
    
    begin_phase("app_factory")
    try:
        app = FastAPI(
            title="GlassyTrade AI",
            description="Algorithmic trading system with AI-driven decision making",
            version="1.0.0",
            lifespan=lifespan,
        )
        end_phase("app_factory", "ok")
    except Exception as e:
        end_phase("app_factory", "failed", str(e))
        mark_startup_failed("runtime", str(e))
        raise

    begin_phase("dependency_bootstrap")
    try:
        # Load configuration — canonical SystemConfig from the YAML loader,
        # identical to app.config.settings (env + strategy), not env-only.
        mode = _settings.get_mode_config()
        config = mode.system_config if mode is not None else None
        logger.info(f"Loaded configuration: {config}")

        # Add CORS middleware
        # Origins loaded from the settings adapter (env CORS_ORIGINS)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_settings.CORS_ORIGINS,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Add correlation ID middleware for request tracing
        app.add_middleware(CorrelationIdMiddleware)
        app.add_middleware(WebSocketLogMiddleware)

        # Initialize DI container from composition root
        from app.application.di.composition_root import compose_container
        container = compose_container(config)

        # Resolve services from container
        broker = container.resolve(IBroker)
        storage = container.resolve(IStorage)
        market_data = container.resolve(IMarketData)

        # Store in app state for backward compatibility
        app.state.runtime_mode = runtime_mode
        app.state.container = container
        app.state.graph = container  # Alias for backward compatibility
        app.state.service_graph = container
        app.state.market_data = market_data
        app.state.broker = broker
        app.state.storage = storage

        # Startup reconciliation before readiness contract assembly
        reconciliation_result = None
        reconciliation_executed = True
        try:
            begin_phase("startup_reconciliation")
            reconciliation = StartupReconciliation(broker, storage)
            reconciliation_result = reconciliation.reconcile()
            record_startup_reconciliation(reconciliation_result)
            end_phase(
                "startup_reconciliation",
                "ok",
                f"db={reconciliation_result.db_positions} broker={reconciliation_result.broker_positions}",
            )
            if (
                runtime_mode == "live"
                and reconciliation_result.db_positions != reconciliation_result.broker_positions
            ):
                # ponytail: refuse to boot on broker/DB position mismatch in live.
                raise RuntimeError(
                    "Startup reconciliation mismatch in live mode: "
                    f"db={reconciliation_result.db_positions} "
                    f"broker={reconciliation_result.broker_positions}"
                )
        except Exception as e:
            reconciliation_executed = False
            logger.warning("Startup reconciliation failed: %s", e)
            record_startup_reconciliation(None)
            end_phase("startup_reconciliation", "failed", str(e))
            mark_startup_failed("startup_reconciliation", str(e))
            if runtime_mode == "live":
                # ponytail: refuse to boot on unknown broker state in live mode.
                # Raising kills startup; the operator must fix reconciliation first.
                raise RuntimeError(
                    f"Startup reconciliation failed in live mode: {e}"
                ) from e

        # Get active symbols from service or config
        active_symbols = list(getattr(app.state, "active_symbols", []))
        if not active_symbols:
            active_symbols = list(_settings.DHAN_SYMBOLS)

        app.state.startup_reconciliation = reconciliation_result
        app.state.active_symbols = tuple(active_symbols)
        app.state.broker = broker
        app.state.storage = storage
        app.state.startup_contracts = _build_startup_contracts(
            broker=broker,
            storage=storage,
            active_symbols=active_symbols,
            coordinator=getattr(app.state, "coordinator", None),
            engine_start_failed=getattr(app.state, "engine_start_failed", False),
            reconciliation_result=reconciliation_result,
            reconciliation_executed=reconciliation_executed,
        )
        app.state.startup_dependency_refs = MappingProxyType(
            {
                "broker": broker,
                "storage": storage,
                "market_data": market_data,
            }
        )

        # Initialize singletons for FastAPI dependencies
        init_singletons(
            broker=broker,
            storage=storage,
            market_data=market_data,
            configuration=config,
            active_symbols=active_symbols,
            coordinator=getattr(app.state, "coordinator", None),
        )

        # Register routers
        app.include_router(health_router, prefix="", tags=["health"])
        app.include_router(health_router, prefix="/api", tags=["health"])
        app.include_router(market_router, prefix="/api", tags=["market"])
        app.include_router(analysis_router, prefix="/api", tags=["analysis"])
        app.include_router(trading_router, prefix="/api", tags=["trading"])
        app.include_router(gameloop_router, prefix="/api", tags=["websocket"])
        app.include_router(journal_router, prefix="/api", tags=["journal"])
        # Dev-only tick injection for cross-process E2E. The router itself
        # re-checks GLASSYTRADE_ENV per request (defense in depth).
        app.include_router(testing_router, prefix="/api")
        app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
        app.include_router(observability_router, prefix="/api", tags=["observability"])
        app.include_router(alerts_router, prefix="/api", tags=["alerts"])
        end_phase("dependency_bootstrap", "ok")
    except Exception as e:
        end_phase("dependency_bootstrap", "failed", str(e))
        mark_startup_failed("runtime", str(e))
        raise

    end_phase("application_init", "ok")
    return app


# Create the FastAPI app at module level for Uvicorn
app = create_application()