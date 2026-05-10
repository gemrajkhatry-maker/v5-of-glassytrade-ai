"""FastAPI runtime control and event streaming API.

Thin HTTP layer — all bootstrap logic lives in app.bootstrap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import List

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
    rl_router,
    scanner_router,
    trading_router,
)
from app.api.websocket import gameloop_router
from app.application.commands.trading_commands import UpdateTick
from app.application.handlers.update_tick_handler import UpdateTickHandler
from app.bootstrap import create_lifespan
from app.infrastructure.messaging.event_bus import EventBus
from app.infrastructure.serialization import OHLCDataDTO

logger = logging.getLogger(__name__)

# ── Event bus (module-level, wired once) ──────────────────────────────────
event_bus = EventBus()
from app.application.event_subscribers import wire_event_bus_subscribers

wire_event_bus_subscribers(event_bus)

# ── Connected SSE clients ─────────────────────────────────────────────────
connected_clients: List[asyncio.Queue] = []

# ── FastAPI Application ───────────────────────────────────────────────────
app = FastAPI(
    title="GlassyTrade AI BackendV2 API",
    description="Runtime control API",
    version="2.0.0",
    lifespan=create_lifespan,
)

app.state.connected_clients = connected_clients

# ── CORS ──────────────────────────────────────────────────────────────────
_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_cors_origins = [item.strip() for item in _cors_origins_env.split(",") if item.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────
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
                        "data": json.dumps({"timestamp": datetime.now(UTC).isoformat()}),
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
        timestamp=float(tick.timestamp or datetime.now(UTC).timestamp()),
        price=tick.close,
        volume=tick.volume,
    )
    handler = UpdateTickHandler(event_bus=event_bus)
    handler.handle(cmd)

    event_data = {
        "type": "tick",
        "symbol": cmd.symbol,
        "price": cmd.price,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    for queue in connected_clients:
        await queue.put(event_data)

    return {"status": "processed", "symbol": cmd.symbol}
