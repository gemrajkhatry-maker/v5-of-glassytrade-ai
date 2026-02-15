"""GlassyTrade AI Backend — FastAPI application entry point.

Production-grade DDD / Event-Driven architecture.
Service graph is created once at startup via the DI factory.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

# API routers
from app.api.routers.health import router as health_router
from app.api.routers.market import router as market_router
from app.api.routers.analysis import router as analysis_router
from app.api.routers.trading import router as trading_router
from app.api.routers.ai import router as ai_router
from app.api.routers.rl import router as rl_router
from app.api.websocket.gameloop import router as gameloop_router

app = FastAPI(
    title="GlassyTrade AI",
    description="Production-grade quant trading backend — DDD / Event-Driven",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(health_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(trading_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(rl_router, prefix="/api")
app.include_router(gameloop_router, prefix="/api")
