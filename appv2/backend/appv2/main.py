"""FastAPI Application — AMT Live Trading System v2.

Wires:
  TradingEngine (full stack) + Dhan adapters + WebSocket game-loop
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from appv2 import __version__
from appv2.config.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle."""
    logger.info("=" * 60)
    logger.info("AMT Live Trading System v%s starting", __version__)
    logger.info("Exchange: %s | Live: %s | Symbols: %s",
                settings.EXCHANGE, settings.LIVE_TRADING, settings.SYMBOLS)
    logger.info("Capital: ₹%.0f | Risk/trade: %.1f%% | Max daily loss: %.1f%%",
                settings.CAPITAL, settings.RISK_PER_TRADE_PCT, settings.MAX_DAILY_LOSS_PCT)
    logger.info("=" * 60)

    if not settings.LIVE_TRADING:
        logger.warning("PAPER TRADING MODE — no real orders will be placed")

    from appv2.application.trading_engine import TradingEngine

    # Create broker adapter (live or paper)
    broker = None
    storage = None
    option_chain_fetcher = None

    if settings.LIVE_TRADING or settings.DHAN_ACCESS_TOKEN != "your_access_token_here":
        try:
            from appv2.infrastructure.dhan_feed import DhanMarketDataAdapter
            from appv2.infrastructure.dhan_executor import DhanExecutorAdapter
            from appv2.infrastructure.option_chain_fetcher import OptionChainFetcher
            from appv2.infrastructure.sqlite_storage import SQLiteStorageAdapter

            broker = DhanExecutorAdapter(
                access_token=settings.DHAN_ACCESS_TOKEN,
                client_id=settings.DHAN_CLIENT_ID,
                live=settings.LIVE_TRADING,
            )
            storage = SQLiteStorageAdapter()
            option_chain_fetcher = OptionChainFetcher(
                access_token=settings.DHAN_ACCESS_TOKEN,
                client_id=settings.DHAN_CLIENT_ID,
            )
            logger.info("Dhan broker adapter initialized")
        except Exception as e:
            logger.warning("Failed to initialize Dhan broker (%s), using paper mode", e)

    engine = TradingEngine(
        broker=broker,
        storage=storage,
        option_chain_fetcher=option_chain_fetcher,
        telegram_token="",
        telegram_chat_id="",
    )

    # Register symbols
    for symbol in settings.symbols_list:
        underlying = symbol
        engine.add_symbol(symbol, underlying=underlying, tick_size=0.05)

    # Start engine (stream, broadcast, reconciliation loops)
    await engine.start()
    app.state.trading_engine = engine

    logger.info("TradingEngine initialized with %d symbols", len(settings.symbols_list))

    yield

    await engine.stop()
    logger.info("AMT Live Trading System shutting down")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="AMT Live Trading System",
        version=__version__,
        description="Fabio Valentini AMT strategy for Indian options trading",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Error handling
    from appv2.api.middleware import error_handler_middleware
    app.middleware("http")(error_handler_middleware)

    # ── Health ──────────────────────────────────────────────────────
    @app.get("/api/v2/health")
    async def health_check():
        engine = getattr(app.state, "trading_engine", None)
        return {
            "status": "ok" if engine and engine.is_running else "starting",
            "version": __version__,
            "live_trading": settings.LIVE_TRADING,
            "exchange": settings.EXCHANGE,
            "symbols": settings.symbols_list,
            "ticks_processed": engine.tick_count if engine else 0,
            "ws_clients": engine.broadcaster.client_count if engine else 0,
            "stream_connected": engine.stream.is_connected if engine else False,
            "uptime_seconds": round(time.time() - app.state.start_time, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── Market ──────────────────────────────────────────────────────
    @app.get("/api/v2/market/symbols")
    async def get_symbols():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            return {
                "symbols": engine.stream.symbols,
                "state_snapshot": engine.broadcaster._last_state,
                "stream_health": engine.stream.get_health().__dict__ if engine.stream else {},
            }
        return {"symbols": settings.symbols_list}

    # ── Signals ─────────────────────────────────────────────────────
    @app.get("/api/v2/signals/active")
    async def get_active_signals():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            trades = engine.trade_lifecycle.get_open_trades()
            return {
                "signals": [],
                "positions": [t.to_dict() for t in trades],
            }
        return {"signals": [], "positions": []}

    @app.get("/api/v2/signals/history")
    async def get_signal_history():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            closed = engine.trade_lifecycle.get_closed_trades()
            return {"signals": [t.to_dict() for t in closed]}
        return {"signals": []}

    # ── Positions ───────────────────────────────────────────────────
    @app.get("/api/v2/positions/open")
    async def get_open_positions():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            trades = engine.trade_lifecycle.get_open_trades()
            return {"positions": [t.to_dict() for t in trades]}
        return {"positions": []}

    @app.get("/api/v2/positions/history")
    async def get_position_history():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            closed = engine.trade_lifecycle.get_closed_trades(limit=100)
            return {"positions": [t.to_dict() for t in closed]}
        return {"positions": []}

    # ── Session State ───────────────────────────────────────────────
    @app.get("/api/v2/state")
    async def get_session_state():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            return engine.session_state.get_all_states()
        return {}

    # ── Analytics ───────────────────────────────────────────────────
    @app.get("/api/v2/analytics")
    async def get_analytics():
        engine = getattr(app.state, "trading_engine", None)
        if engine:
            stats = engine.analytics.compute_stats()
            return stats.__dict__
        return {}

    # ── WebSocket Game-Loop ─────────────────────────────────────────
    @app.websocket("/api/v2/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        engine: "TradingEngine" = getattr(app.state, "trading_engine", None)

        if not engine:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Engine not started",
            }))
            await websocket.close()
            return

        broadcaster = engine.broadcaster
        broadcaster.add_client(websocket)

        try:
            # Send initial sync
            await broadcaster.send_initial_sync(
                websocket, broadcaster._last_state,
            )

            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)

                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg.get("type") == "subscribe":
                    symbols = msg.get("symbols", [])
                    await engine.stream.subscribe(symbols)

        except WebSocketDisconnect:
            broadcaster.remove_client(websocket)
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            broadcaster.remove_client(websocket)

    app.state.start_time = time.time()
    return app


app = create_app()
