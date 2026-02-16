"""GlassyTrade AI Backend — FastAPI application entry point.

Production-grade DDD / Event-Driven architecture.
Service graph is created once at startup via the DI factory.
LLM model is loaded and validated before the server accepts connections.
"""

from __future__ import annotations

import logging
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_setup_logging()

log = logging.getLogger(__name__)

# API routers
from app.api.routers.health import router as health_router
from app.api.routers.market import router as market_router
from app.api.routers.analysis import router as analysis_router
from app.api.routers.trading import router as trading_router
from app.api.routers.ai import router as ai_router
from app.api.routers.rl import router as rl_router
from app.api.websocket.gameloop import router as gameloop_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: eagerly create service graph and wait for LLM model readiness."""
    from app.api.dependencies import get_service_graph

    log.info("Creating service graph and loading LLM model...")
    graph = get_service_graph()
    llm = graph.llm_inference

    # Block until model is loaded (up to 120s)
    log.info("Waiting for LLM model to be ready (up to 120s)...")
    ready = llm.wait_until_ready(timeout=120.0)
    if not ready:
        log.error("LLM model failed to load within timeout! Backend will start but LLM calls will fail.")
    else:
        # Validate with a test inference
        log.info("Running LLM validation inference...")
        valid = llm.validate()
        if valid:
            log.info("LLM model loaded and validated — backend ready for trading.")
        else:
            log.error("LLM validation inference failed! Model may produce bad outputs.")

    yield  # Server is running

    log.info("Shutting down GlassyTrade AI backend.")


app = FastAPI(
    title="GlassyTrade AI",
    description="Production-grade quant trading backend — DDD / Event-Driven",
    version="2.0.0",
    lifespan=lifespan,
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
