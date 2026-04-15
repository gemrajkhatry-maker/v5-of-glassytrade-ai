#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Main application entry point.

This module sets up the dependency injection graph and starts the FastAPI application.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator


def _apply_repo_dotenv_fill_blanks() -> None:
    """Fill unset or blank os.environ keys from repo-root .env (shell `export VAR=` cannot block)."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    repo = Path(__file__).resolve().parent.parent.parent
    env_path = repo / ".env"
    if not env_path.is_file():
        return
    for key, val in dotenv_values(env_path).items():
        if val is None:
            continue
        sval = str(val).strip()
        if not sval:
            continue
        cur = os.environ.get(key)
        if cur is None or (isinstance(cur, str) and not cur.strip()):
            os.environ[key] = sval


_apply_repo_dotenv_fill_blanks()

# Avoid OpenMP/runtime clashes when MLX and LightGBM both load in one process (macOS).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import set_service_graph
from app.api.routers import (
    health_router,
    market_router,
    trading_router,
    ai_router,
    rl_router,
    metrics_router,
)
from app.api.websocket.gameloop import router as gameloop_router
from app.application.service_graph import ServiceGraph
from config.config import Configuration

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        """Application lifespan: startup and shutdown."""
        # Startup
        logger.info("Starting GlassyTrade AI application...")
        
        # Get service graph from app state
        graph = app.state.service_graph
        
        # Run option scanner to select MCX/NSE contracts
        logger.info("Running option scanner to select contracts...")
        try:
            from app.domain.fabio_ai.services.option_scanner import OptionScannerService
            from app.config import settings

            scanner = OptionScannerService(graph.market_data)

            # Run synchronous scanner off the event loop (avoid Future.result() blocking the loop)
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    scanner.scan_top_n,
                    n=settings.SCANNER_TOP_N,
                    underlyings=settings.SCANNER_UNDERLYINGS,
                    preferred_option_type=settings.SCANNER_OPTION_TYPE or None,
                    exchange=settings.DEFAULT_EXCHANGE,
                    expiry_index=settings.SCANNER_EXPIRY_INDEX,
                    strikes_around_atm=settings.STRIKES_AROUND_ATM,
                ),
                timeout=120.0,
            )
            
            if results:
                # Filter to valid contracts with LTP > 0
                final = [r for r in results if r.ltp > 0] or results
                selected_symbols = [r.symbol for r in final[:settings.SCANNER_TOP_N]]
                
                if selected_symbols:
                    graph.active_symbols = selected_symbols
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
                    graph.active_symbols
                )
        except Exception as e:
            logger.error("Option scanner failed: %s — using default underlyings", e, exc_info=True)
        
        # Start the trading engine
        from app.application.engine import TradingEngine
        engine = TradingEngine(graph)
        graph.engine = engine
        
        try:
            await engine.start()
            logger.info("Trading engine started — backend trades independently of frontend.")
        except Exception:
            logger.error("Trading engine failed to start!", exc_info=True)
        
        logger.info("Application started successfully")
        
        yield  # Server is running
        
        # Shutdown
        logger.info("Shutting down GlassyTrade AI application...")
        
        # Stop trading engine
        if graph.engine:
            try:
                await graph.engine.stop()
                logger.info("Trading engine stopped")
            except Exception:
                logger.debug("Engine stop failed", exc_info=True)
        
        logger.info("Shutdown complete")
    
    app = FastAPI(
        title="GlassyTrade AI",
        description="Algorithmic trading system with AI-driven decision making",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Add CORS middleware
    # NOTE: For WebSocket connections, we need to use allow_origin_regex instead of
    # allow_origins=["*"] when allow_credentials=True, otherwise WS connections get 403
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins for development
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add WebSocket logging middleware to debug 403 issues
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class WebSocketLogMiddleware(BaseHTTPMiddleware):
        """Log WebSocket connection attempts for debugging."""
        async def dispatch(self, request: Request, call_next):
            if request.url.path == "/api/trading/ws/gameloop":
                logger.info(
                    "WebSocket request: method=%s, path=%s, headers=%s",
                    request.method,
                    request.url.path,
                    dict(request.headers)
                )
            response = await call_next(request)
            return response

    app.add_middleware(WebSocketLogMiddleware)

    # Load configuration
    config = Configuration.from_env()
    logger.info(f"Loaded configuration: {config}")

    # Create service graph
    service_graph = ServiceGraph(config)

    # Store service graph in application state
    app.state.service_graph = service_graph
    app.state.engine = None  # Will be set by lifespan
    set_service_graph(service_graph)

    # Register routers
    app.include_router(health_router, prefix="", tags=["health"])
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(market_router, prefix="/market", tags=["market"])
    app.include_router(trading_router, prefix="/trading", tags=["trading"])
    app.include_router(gameloop_router, prefix="/api", tags=["websocket"])
    app.include_router(ai_router, prefix="/api", tags=["ai"])
    app.include_router(rl_router, prefix="/rl", tags=["rl"])
    app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])

    return app


async def startup_event(service_graph: ServiceGraph):
    """Application startup event."""
    logger.info("Starting GlassyTrade AI application...")

    # Initialize services that need setup
    # Example: market_data_adapter = service_graph.get(IMarketData)
    # market_data_adapter.ensure_initialized_sync()

    logger.info("Application started successfully")


async def shutdown_event(service_graph: ServiceGraph):
    """Application shutdown event."""
    logger.info("Shutting down GlassyTrade AI application...")

    # Cleanup resources
    # Example: market_data_adapter = service_graph.get(IMarketData)
    # market_data_adapter.close_sync()

    logger.info("Shutdown complete")


def main() -> None:
    """Main entry point."""
    try:
        logger.info("Created FastAPI application")
    except Exception as e:
        logger.error(f"Failed to create application: {e}")
        sys.exit(1)


# Create the FastAPI app at module level for Uvicorn
app = create_application()


if __name__ == "__main__":
    main()
