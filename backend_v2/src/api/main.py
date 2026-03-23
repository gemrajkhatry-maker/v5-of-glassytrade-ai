"""
FastAPI app factory — REST + WebSocket endpoints.

Creates and configures the FastAPI application.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from src.api.routers import signals, profiles, risk, trades, config_router
from src.output.ws_publisher import WSPublisher
from src.output.metrics import init_metrics

logger = structlog.get_logger()

# Global WebSocket publisher
ws_publisher = WSPublisher()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    logger.info("api_server_starting")
    init_metrics()
    yield
    logger.info("api_server_stopping")


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Returns:
        Configured FastAPI app.
    """
    app = FastAPI(
        title="GlassyTrade AI V2",
        description="AMT Order Flow Strategy Engine",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(signals.router, prefix="/api", tags=["signals"])
    app.include_router(profiles.router, prefix="/api", tags=["profiles"])
    app.include_router(risk.router, prefix="/api", tags=["risk"])
    app.include_router(trades.router, prefix="/api", tags=["trades"])
    app.include_router(config_router.router, prefix="/api", tags=["config"])

    # Prometheus metrics endpoint
    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )

    # WebSocket endpoint
    @app.websocket("/ws/signals")
    async def websocket_signals(websocket: WebSocket):
        """WebSocket endpoint for real-time signal broadcasting."""
        await ws_publisher.connect(websocket)
        try:
            while True:
                # Keep connection alive
                data = await websocket.receive_text()
                # Echo back for heartbeat
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            await ws_publisher.disconnect(websocket)

    return app


# Create app instance
app = create_app()