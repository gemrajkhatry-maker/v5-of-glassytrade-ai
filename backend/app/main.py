#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Main application entry point.

This module sets up the dependency injection graph and starts the FastAPI application.
"""

import faulthandler
from contextlib import asynccontextmanager
from pathlib import Path
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
    ai_router,
    rl_router,
    metrics_router,
)
from app.api.routers.observability import router as observability_router
from app.api.routers.alerts import router as alerts_router
from app.api.routers.analysis import router as analysis_router
from app.api.websocket.gameloop import router as gameloop_router
from app.api.dependencies import init_singletons
from app.core.correlation import CorrelationIdMiddleware
from app.core.logging import setup_logging, get_logger
from config.consolidated import ConsolidatedConfig as Configuration
from app.domain.ports.broker import IBroker
from app.domain.ports.storage import IStorage
from app.domain.ports.market_data import IMarketData
from app.domain.ports.llm_inference import ILLMInference
from app.application.services.trading_session import TradingSessionService

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
    
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        """Application lifespan: startup and shutdown."""
        # Startup
        logger.info("Starting GlassyTrade AI application...")

        # Get service container from app state
        container = app.state.container

        # Run option scanner to select MCX/NSE contracts
        logger.info("Running option scanner to select contracts...")
        try:
            from app.domain.fabio_ai.services.option_scanner import OptionScannerService
            from app.config import settings
            import concurrent.futures

            scanner = OptionScannerService(container.resolve(IMarketData))

            # Run scanner in thread pool (it's synchronous)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                results = pool.submit(
                    scanner.scan_top_n,
                    n=settings.SCANNER_TOP_N,
                    underlyings=settings.SCANNER_UNDERLYINGS,
                    preferred_option_type=settings.SCANNER_OPTION_TYPE or None,
                    exchange=settings.DEFAULT_EXCHANGE,
                    expiry_index=settings.SCANNER_EXPIRY_INDEX,
                    strikes_around_atm=settings.STRIKES_AROUND_ATM,
                ).result(timeout=120)

            if results:
                # Filter to valid contracts with LTP > 0
                final = [r for r in results if r.ltp > 0] or results
                selected_symbols = [r.symbol for r in final[:settings.SCANNER_TOP_N]]

                if selected_symbols:
                    container.register_singleton(list, lambda c: selected_symbols)
                    app.state.active_symbols = selected_symbols
                    logger.info(
                        "Option scanner selected %d contracts: %s",
                        len(selected_symbols),
                        selected_symbols
                    )
                else:
                    logger.warning("Option scanner found contracts but none with LTP > 0")
            else:
                logger.warning(
                    "Option scanner found no contracts — using default underlyings: %s",
                    app.state.active_symbols
                )
        except Exception as e:
            logger.error("Option scanner failed: %s — using default underlyings", e, exc_info=True)

        # Start the trading engine
        from app.application.engine import TradingEngine
        engine = TradingEngine(container)
        app.state.engine = engine

        try:
            await engine.start()
            logger.info("Trading engine started — backend trades independently of frontend.")
        except Exception:
            logger.error("Trading engine failed to start!", exc_info=True)
            app.state.engine_start_failed = True

        logger.info("Application started successfully")

        yield  # Server is running

        # Shutdown
        logger.info("Shutting down GlassyTrade AI application...")

        # Stop trading engine
        if app.state.engine:
            try:
                await app.state.engine.stop()
                logger.info("Trading engine stopped")
            except Exception:
                logger.error("Engine stop failed — resources may not be cleaned up", exc_info=True)

        # Cleanup handler thread pools (LLMEntryHandler, LLMOverseerHandler)
        try:
            app.state.trading_session.cleanup()
            logger.info("Handler thread pools cleaned up")
        except Exception:
            logger.debug("Handler cleanup failed — non-critical", exc_info=True)

        logger.info("Shutdown complete")
    
    app = FastAPI(
        title="GlassyTrade AI",
        description="Algorithmic trading system with AI-driven decision making",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Load configuration — must match app.config.settings (YAML strategy + MCX/NSE), not env-only.
    config = Configuration.from_unified()
    logger.info(f"Loaded configuration (unified): {config}")

    # Add CORS middleware
    # Origins loaded from configuration (consolidated.py)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
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
    trading_session = container.resolve(TradingSessionService)
    broker = container.resolve(IBroker)
    storage = container.resolve(IStorage)
    market_data = container.resolve(IMarketData)
    
    # Store in app state for backward compatibility
    app.state.container = container
    app.state.graph = container  # Alias for backward compatibility
    app.state.service_graph = container
    app.state.trading_session = trading_session
    app.state.market_data = market_data
    app.state.broker = broker
    app.state.storage = storage
    
    # Get active symbols from service or config
    active_symbols = list(getattr(config, "dhan_symbols", []))
    if not active_symbols:
        from app.config import settings as _settings
        active_symbols = list(getattr(_settings, "DHAN_SYMBOLS", []))
    app.state.active_symbols = active_symbols
    
    # Initialize singletons for FastAPI dependencies
    init_singletons(
        trading_session=trading_session,
        broker=broker,
        storage=storage,
        gen_ai_service=container.resolve(ILLMInference),
        market_data=market_data,
        configuration=config,
        active_symbols=active_symbols,
    )

    # Register routers
    app.include_router(health_router, prefix="", tags=["health"])
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(market_router, prefix="/api", tags=["market"])
    app.include_router(analysis_router, prefix="/api", tags=["analysis"])
    app.include_router(trading_router, prefix="/api", tags=["trading"])
    app.include_router(gameloop_router, prefix="/api", tags=["websocket"])
    app.include_router(ai_router, prefix="/api", tags=["ai"])
    app.include_router(rl_router, prefix="/rl", tags=["rl"])
    app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
    app.include_router(observability_router, prefix="/api", tags=["observability"])
    app.include_router(alerts_router, prefix="/api", tags=["alerts"])

    return app


# Create the FastAPI app at module level for Uvicorn
app = create_application()