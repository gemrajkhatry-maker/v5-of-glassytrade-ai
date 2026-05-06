"""Routers for BackendV2 public API."""

from app.api.routers.ai import router as ai_router
from app.api.routers.alerts import router as alerts_router
from app.api.routers.health import router as health_router
from app.api.routers.market import router as market_router
from app.api.routers.observability import router as observability_router
from app.api.routers.metrics import router as metrics_router
from app.api.routers.analysis import router as analysis_router
from app.api.routers.rl import router as rl_router
from app.api.routers.trading import router as trading_router
from app.api.routers.scanner import router as scanner_router

__all__ = [
    "ai_router",
    "alerts_router",
    "health_router",
    "market_router",
    "analysis_router",
    "trading_router",
    "metrics_router",
    "observability_router",
    "rl_router",
    "scanner_router",
]
