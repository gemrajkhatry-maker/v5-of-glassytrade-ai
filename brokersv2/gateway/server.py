"""Gateway Server - FastAPI production server with observability."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from brokersv2.observability.metrics import MetricsCollector
from brokersv2.observability.health import (
    HealthChecker,
    HealthStatus,
    HealthCheck,
    CheckType,
)

logger = logging.getLogger(__name__)

# Version
__version__ = "1.0.0"


class GatewayConfig:
    """Gateway server configuration."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9090,
        debug: bool = False,
        cors_origins: list[str] = None,
    ):
        self.host = host
        self.port = port
        self.debug = debug
        self.cors_origins = cors_origins or ["*"]


class AppState:
    """Application state holder."""

    def __init__(self):
        self.metrics = MetricsCollector()
        self.health_checker = HealthChecker()
        self.config: Optional[GatewayConfig] = None
        self.startup_time: Optional[datetime] = None


def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    """
    Create and configure FastAPI gateway application.
    
    Args:
        config: Gateway configuration
        
    Returns:
        Configured FastAPI application
    """
    if config is None:
        config = GatewayConfig()

    # Create app state
    state = AppState()
    state.config = config
    state.startup_time = datetime.now(timezone.utc)

    # Register default health checks
    state.health_checker.register_check(
        HealthCheck(name="process", check_type=CheckType.LIVENESS, critical=True)
    )
    state.health_checker.register_check(
        HealthCheck(name="database", check_type=CheckType.READINESS, critical=True)
    )

    # Set initial health results
    state.health_checker.update_result("process", HealthStatus.HEALTHY, "Running")
    state.health_checker.update_result("database", HealthStatus.HEALTHY, "Connected")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan - startup and shutdown."""
        # Startup
        logger.info(f"Starting GlassyTrade Gateway v{__version__}")
        logger.info(f"Listening on {config.host}:{config.port}")

        # Record metrics
        state.metrics.increment("gateway_starts", description="Gateway startup count")

        yield

        # Shutdown
        logger.info("Shutting down GlassyTrade Gateway")
        state.metrics.increment("gateway_stops", description="Gateway shutdown count")

    # Create FastAPI app
    app = FastAPI(
        title="GlassyTrade Gateway",
        description="Production trading platform gateway",
        version=__version__,
        lifespan=lifespan,
    )

    # Store state
    app.state.metrics = state.metrics
    app.state.health_checker = state.health_checker
    app.state.config = state.config

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    _register_routes(app, state)

    logger.info(f"Gateway app created: {config.host}:{config.port}")
    return app


def _register_routes(app: FastAPI, state: AppState):
    """Register all routes."""

    # Health endpoints
    @app.get("/health")
    async def health():
        """Overall health check."""
        overall = state.health_checker.get_overall_status()
        return {
            "status": overall["overall"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": overall,
        }

    @app.get("/health/liveness")
    async def liveness():
        """Liveness probe - is process alive?"""
        result = state.health_checker.check_liveness()
        return {
            "status": result.status.value,
            "message": result.message,
            "is_overall_healthy": result.is_overall_healthy,
            "timestamp": result.timestamp.isoformat(),
        }

    @app.get("/health/readiness")
    async def readiness():
        """Readiness probe - are dependencies ready?"""
        result = state.health_checker.check_readiness()
        return {
            "status": result.status.value,
            "message": result.message,
            "is_overall_healthy": result.is_overall_healthy,
            "timestamp": result.timestamp.isoformat(),
        }

    # Metrics endpoint (Prometheus format)
    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics():
        """Prometheus metrics endpoint."""
        # Add runtime metrics
        if state.startup_time:
            uptime = (datetime.now(timezone.utc) - state.startup_time).total_seconds()
            state.metrics.set_gauge("gateway_uptime_seconds", uptime)

        return state.metrics.format_prometheus()

    # Server info
    @app.get("/info")
    async def info():
        """Server information."""
        uptime = 0
        if state.startup_time:
            uptime = (datetime.now(timezone.utc) - state.startup_time).total_seconds()

        return {
            "service": "glassytrade-gateway",
            "version": __version__,
            "uptime_seconds": uptime,
            "config": {
                "host": state.config.host,
                "port": state.config.port,
                "debug": state.config.debug,
            },
        }

    # Risk status
    @app.get("/risk/status")
    async def risk_status():
        """Current risk status."""
        state.metrics.increment("risk_status_requests", description="Risk status API calls")

        return {
            "kill_switch_active": False,
            "exposure": {
                "total": 0,
                "open_orders": 0,
            },
            "positions_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Positions
    @app.get("/positions")
    async def positions():
        """Current positions."""
        state.metrics.increment("positions_requests", description="Positions API calls")

        return {
            "positions": [],
            "total_exposure": 0,
            "count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Orders
    @app.get("/orders")
    async def orders():
        """Current orders."""
        state.metrics.increment("orders_requests", description="Orders API calls")

        return {
            "orders": [],
            "total": 0,
            "filters": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Middleware for request tracking
    @app.middleware("http")
    async def track_requests(request, call_next):
        """Track all requests with metrics."""
        start_time = datetime.now(timezone.utc)

        # Increment request counter
        state.metrics.increment(
            "http_requests_total",
            labels={"method": request.method, "path": request.url.path},
        )

        response = await call_next(request)

        # Track response time
        elapsed_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        state.metrics.observe(
            "http_request_duration_ms",
            elapsed_ms,
            labels={"method": request.method, "path": request.url.path},
        )

        return response
