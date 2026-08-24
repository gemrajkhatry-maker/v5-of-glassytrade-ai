# API routers.

from app.api.routers.health import router as health_router
from app.api.routers.market import router as market_router
from app.api.routers.trading import router as trading_router
from app.api.routers.ai import router as ai_router
from app.api.routers.rl import router as rl_router
from app.api.routers.metrics import router as metrics_router

__all__ = [
    "health_router",
    "market_router",
    "trading_router",
    "ai_router",
    "rl_router",
    "metrics_router",
]

