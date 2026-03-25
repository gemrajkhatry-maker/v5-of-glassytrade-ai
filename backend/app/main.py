"""GlassyTrade AI Backend — FastAPI application entry point.

Production-grade DDD / Event-Driven architecture.
Service graph is created once at startup via the DI factory.
LLM model is loaded and validated before the server accepts connections.
"""

from __future__ import annotations

import logging
import json
import sys
import os

# Fix OpenMP multiple initialization crash (LightGBM + MLX) on macOS
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import time as _time
import tracemalloc
from collections import defaultdict

if os.getenv("DEBUG_MEMORY", "").lower() == "true":
    tracemalloc.start()
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
from app.api.routers.metrics import router as metrics_router
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
        log.error(
            "LLM model failed to load within timeout! Backend will start but LLM calls will fail."
        )
    else:
        # Validate with a test inference
        log.info("Running LLM validation inference...")
        valid = llm.validate()
        if valid:
            log.info("LLM model loaded and validated — backend ready for trading.")
        else:
            log.error("LLM validation inference failed! Model may produce bad outputs.")

    # Start the standalone trading engine (trades independently of frontend)
    from app.application.engine import TradingEngine

    engine = TradingEngine(graph)
    graph.engine = engine
    try:
        await engine.start()
        log.info("Trading engine started — backend trades independently of frontend.")
    except Exception:
        log.error("Trading engine failed to start!", exc_info=True)

    yield  # Server is running

    # Graceful shutdown
    log.info("Shutting down GlassyTrade AI backend...")

    # Stop trading engine first
    if graph.engine:
        try:
            await graph.engine.stop()
        except Exception:
            log.debug("Engine stop failed", exc_info=True)

    # Flush pending database ticks
    try:
        storage = graph.storage
        if hasattr(storage, "_flush_ticks"):
            try:
                storage._flush_ticks()
            except Exception:
                pass
    except Exception:
        log.debug("Tick flush on shutdown failed", exc_info=True)

    # Shutdown handler thread pools via cleanup()
    try:
        ts = graph.trading_session
        for attr in ("_llm_handler", "_overseer_handler"):
            handler = getattr(ts, attr, None)
            if handler and hasattr(handler, "cleanup"):
                handler.cleanup()
        log.info("Thread pools shut down.")
    except Exception:
        log.debug("Thread pool cleanup failed", exc_info=True)


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

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (100 req/min per client IP)
# ---------------------------------------------------------------------------
_request_counts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 100  # max requests per window
_RATE_WINDOW = 60  # window in seconds


@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    """Reject requests exceeding _RATE_LIMIT per _RATE_WINDOW seconds."""
    client_ip = request.client.host if request.client else "unknown"
    now = _time.time()
    # Evict timestamps outside the current window
    _request_counts[client_ip] = [
        t for t in _request_counts[client_ip] if now - t < _RATE_WINDOW
    ]
    if len(_request_counts[client_ip]) >= _RATE_LIMIT:
        from starlette.responses import JSONResponse

        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
    _request_counts[client_ip].append(now)
    return await call_next(request)


# Mount routers
app.include_router(health_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(trading_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(rl_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(gameloop_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9090)
