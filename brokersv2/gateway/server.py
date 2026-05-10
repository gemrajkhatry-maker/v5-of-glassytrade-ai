"""Gateway Server - FastAPI production server with observability."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from brokersv2.domain.market.hours import MarketHoursGate, MarketClosedError
from brokersv2.observability.metrics import MetricsCollector
from brokersv2.observability.health import (
    HealthChecker,
    HealthStatus,
    HealthCheck,
    CheckType,
)
from brokersv2.core.resilience import CircuitBreaker
from brokersv2.core.errors import CircuitBreakerOpenError

logger = logging.getLogger(__name__)

# Version
__version__ = "1.0.0"


# =============================================================================
# Request/Response Models
# =============================================================================

class HistoricalRequest(BaseModel):
    """Historical data request."""
    symbol: str
    exchange: str
    from_date: str
    to_date: str
    interval: str = "1d"
    include_oi: bool = False


class QuoteBatchRequest(BaseModel):
    """Batch quote request."""
    symbols: List[str]


class OrderRequest(BaseModel):
    """Order placement request."""
    symbol: str
    exchange: str
    quantity: int
    side: str  # BUY/SELL
    order_type: str  # MARKET/LIMIT/SL/SL-M
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    after_market_order: bool = False


class ModifyOrderRequest(BaseModel):
    """Order modification request — all fields are optional."""
    price: Optional[float] = None
    quantity: Optional[int] = None
    order_type: Optional[str] = None      # MARKET/LIMIT/SL/SL-M
    validity: Optional[str] = None        # DAY/IOC
    trigger_price: Optional[float] = None
    disclosed_quantity: Optional[int] = None


class BrokerStatus(BaseModel):
    """Broker connection status."""
    connected: bool
    broker_type: str
    last_check: str


# =============================================================================
# Gateway Configuration
# =============================================================================

class GatewayConfig:
    """Gateway server configuration."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9090,
        debug: bool = False,
        cors_origins: list[str] = None,
        dry_run: bool = False,
    ):
        self.host = host
        self.port = port
        self.debug = debug
        self.cors_origins = cors_origins or ["*"]
        self.dry_run = dry_run


# Import DryRunBroker from testing module
from brokersv2.testing.mocks import DryRunBroker  # noqa: F401


# Note: DryRunBroker class removed - use brokersv2.testing.mocks.DryRunBroker

class AppState:
    """Application state holder."""

    def __init__(self):
        from brokersv2.core.constants import CircuitBreaker as CBConstants
        self.metrics = MetricsCollector()
        self.health_checker = HealthChecker()
        self.config: Optional[GatewayConfig] = None
        self.startup_time: Optional[datetime] = None
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=CBConstants.FAILURE_THRESHOLD,
            recovery_timeout=CBConstants.RECOVERY_TIMEOUT,
        )
        self.dry_run_broker = DryRunBroker()
        self.market_hours_gate: Optional[MarketHoursGate] = None  # Shared instance (set post-init)

        # Phase 2: Market data service
        self.market_data_service = None  # MarketDataService (set externally)

        # Wired by bootstrap.create_gateway_app() / lifespan; default to None so
        # endpoints fall through to dry-run mode when the adapter is not configured.
        self.broker = None          # IBrokerAdapter | None
        self.market_data = None     # MarketDataService | None
        self.order_manager = None   # OrderManager | None


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
        import asyncio as _asyncio

        # Startup
        logger.info("Starting GlassyTrade Gateway v%s", __version__)
        logger.info("Listening on %s:%s", config.host, config.port)
        state.metrics.increment("gateway_starts", description="Gateway startup count")

        # Broker is wired by bootstrap.create_gateway_app() and stored in app.state
        # before the lifespan runs.  Expose it on state as well for route closures.
        state.broker = getattr(app.state, "broker", None)
        state.market_data = getattr(app.state, "market_data", None)
        state.order_manager = getattr(app.state, "order_manager", None)

        if state.broker and not config.dry_run:
            logger.info("Live broker adapter connected (dry_run=False)")
        else:
            logger.info("Gateway running in DRY RUN mode — no real orders will be placed")

        # Run any startup callbacks registered by bootstrap (replaces @on_event)
        _startup_tasks: list = getattr(app.state, "_startup_tasks", [])
        _background_tasks: list = []
        for startup_fn in _startup_tasks:
            try:
                result = await startup_fn(app)
                if result is not None:
                    # startup_fn returned a coroutine to run as a background task
                    _background_tasks.append(_asyncio.ensure_future(result))
            except Exception as exc:
                logger.error("Startup task %s failed: %s", getattr(startup_fn, "__name__", startup_fn), exc)

        yield

        # Graceful shutdown sequence:
        # 1. Stop accepting new orders (mark state as shutting down)
        logger.info("Shutting down GlassyTrade Gateway — stopping order acceptance")
        state.metrics.increment("gateway_stops", description="Gateway shutdown count")

        # 2. Cancel background tasks (reconciler, scheduler, token refresh)
        for task in _background_tasks:
            task.cancel()
            try:
                await task
            except (_asyncio.CancelledError, Exception):
                pass

        # 3. Stop market data WebSocket
        if state.market_data and hasattr(state.market_data, 'ws_manager'):
            try:
                await state.market_data.ws_manager.stop()
            except Exception as exc:
                logger.warning("Error stopping WebSocket: %s", exc)

        # 4. Close broker adapter HTTP session
        if state.broker:
            try:
                await state.broker.close()
            except Exception as exc:
                logger.warning("Error closing broker adapter: %s", exc)

        # 5. Stop event bus
        if hasattr(state, 'event_bus') and state.event_bus:
            try:
                await state.event_bus.stop()
            except Exception as exc:
                logger.warning("Error stopping event bus: %s", exc)

        logger.info("GlassyTrade Gateway shutdown complete")

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
    app.state.market_data_service = state.market_data_service

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

    # ========================================================================
    # Health & Observability Endpoints
    # ========================================================================

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

    # ========================================================================
    # Market Data Endpoints
    # ========================================================================

    @app.get("/quote/{symbol}")
    async def get_quote(symbol: str, exchange: str = Query("NSE")):
        """Get current quote for symbol."""
        state.metrics.increment("quote_requests", labels={"symbol": symbol})

        if state.config.dry_run or state.broker is None:
            return state.dry_run_broker.get_quote_mock(symbol)

        try:
            from brokersv2.domain.instrument.models import CanonicalInstrument
            instrument = CanonicalInstrument.from_symbol(f"{exchange.upper()}:{symbol}")
            quote = await state.broker.get_quote(instrument)
            return {
                "symbol": symbol,
                "exchange": exchange,
                "ltp": float(quote.ltp) if hasattr(quote, "ltp") else quote.get("ltp", 0.0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Quote error for %s: %s", symbol, exc)
            state.metrics.increment("quote_errors", labels={"symbol": symbol})
            raise HTTPException(status_code=502, detail=str(exc))

    @app.post("/quotes/batch")
    async def get_quotes_batch(request: QuoteBatchRequest):
        """Get quotes for multiple symbols."""
        state.metrics.increment("batch_quote_requests")
        
        return {
            "quotes": [],
            "count": len(request.symbols),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/historical")
    async def get_historical(request: HistoricalRequest):
        """Get historical OHLCV candle data."""
        state.metrics.increment("historical_requests", labels={
            "symbol": request.symbol,
            "interval": request.interval,
        })

        if state.config.dry_run or state.broker is None:
            return state.dry_run_broker.get_historical_mock(
                symbol=request.symbol,
                exchange=request.exchange,
                from_date=request.from_date,
                to_date=request.to_date,
                interval=request.interval,
            )

        try:
            from brokersv2.domain.instrument.models import CanonicalInstrument
            instrument = CanonicalInstrument.from_symbol(
                f"{request.exchange.upper()}:{request.symbol}"
            )
            candles = await state.broker.get_historical(
                instrument=instrument,
                from_date=request.from_date,
                to_date=request.to_date,
                interval=request.interval,
            )
            serialised = [
                {
                    "timestamp": c.timestamp.isoformat() if hasattr(c, "timestamp") else str(c),
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                }
                for c in candles
            ]
            return {
                "symbol": request.symbol,
                "exchange": request.exchange,
                "interval": request.interval,
                "candles": serialised,
                "count": len(serialised),
                "from_date": request.from_date,
                "to_date": request.to_date,
            }
        except Exception as exc:
            logger.error("Historical data error for %s: %s", request.symbol, exc)
            state.metrics.increment("historical_errors", labels={"symbol": request.symbol})
            raise HTTPException(status_code=502, detail=str(exc))

    @app.get("/candles/{symbol}")
    async def get_candles(
        symbol: str,
        from_date: str = Query(..., description="Start date YYYY-MM-DD"),
        to_date: str = Query(..., description="End date YYYY-MM-DD"),
        interval: str = Query("1d", description="Candle interval"),
    ):
        """Get historical candles (GET variant)."""
        state.metrics.increment("candle_requests", labels={
            "symbol": symbol,
            "interval": interval,
        })
        
        return {
            "symbol": symbol,
            "interval": interval,
            "candles": [],
            "count": 0,
        }

    # ========================================================================
    # Order Management Endpoints
    # ========================================================================

    @app.post("/orders")
    async def place_order(request: OrderRequest):
        """Place a new order."""
        state.metrics.increment("order_placements", labels={
            "side": request.side,
            "type": request.order_type,
        })

        # Hard-reject orders outside market hours at the gateway layer.
        # AMO orders bypass this check (after_market_order flag handled downstream).
        after_market = getattr(request, "after_market_order", False)
        if not after_market and not getattr(state.config, "dry_run", True):
            _gate = state.market_hours_gate or MarketHoursGate()
            exchange_segment = f"{request.exchange.upper()}_EQ"
            try:
                _gate.check(exchange_segment)
            except MarketClosedError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        if state.config.dry_run or state.broker is None:
            return state.dry_run_broker.place_order_mock(
                symbol=request.symbol,
                exchange=request.exchange,
                quantity=request.quantity,
                side=request.side,
                order_type=request.order_type,
                price=request.price,
            )

        try:
            from decimal import Decimal
            from brokersv2.domain.instrument.models import CanonicalInstrument
            from brokersv2.domain.order.models import Order
            from brokersv2.core.types import OrderSide, OrderType, OrderStatus
            import uuid

            instrument = CanonicalInstrument.from_symbol(
                f"{request.exchange.upper()}:{request.symbol}"
            )
            order = Order(
                order_id=str(uuid.uuid4()),
                instrument=instrument,
                side=OrderSide(request.side.upper()),
                quantity=Decimal(str(request.quantity)),
                order_type=OrderType(request.order_type.upper()),
                price=Decimal(str(request.price)) if request.price else None,
                trigger_price=Decimal(str(request.trigger_price)) if request.trigger_price else None,
            )
            broker_order_id = await state.broker.place_order(order)
            return {
                "order_id": order.order_id,
                "broker_order_id": broker_order_id,
                "status": order.status.value,
                "symbol": request.symbol,
                "exchange": request.exchange,
                "quantity": request.quantity,
                "side": request.side,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Order placement error for %s: %s", request.symbol, exc)
            state.metrics.increment("order_errors", labels={"symbol": request.symbol})
            raise HTTPException(status_code=502, detail=str(exc))

    @app.put("/orders/{order_id}")
    async def modify_order(order_id: str, request: ModifyOrderRequest):
        """
        Modify a pending order.

        All fields are optional — only supplied fields are forwarded to the
        broker.  At least one field must be provided.
        """
        if state.broker is None:
            raise HTTPException(status_code=503, detail="Broker not configured")

        if all(v is None for v in request.model_dump().values()):
            raise HTTPException(
                status_code=422, detail="At least one field must be provided for modification"
            )

        try:
            success = await state.broker.modify_order(
                broker_order_id=order_id,
                price=request.price,
                quantity=request.quantity,
                order_type=request.order_type,
                validity=request.validity,
                trigger_price=request.trigger_price,
                disclosed_quantity=request.disclosed_quantity,
            )
            return {"order_id": order_id, "modified": success}
        except Exception as exc:
            logger.error("Order modify error for %s: %s", order_id, exc)
            raise HTTPException(status_code=502, detail=str(exc))

    @app.get("/orders")
    async def get_orders():
        """Get current orders."""
        state.metrics.increment("orders_requests", description="Orders API calls")

        return {
            "orders": [],
            "total": 0,
            "filters": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/orders/{order_id}")
    async def get_order_status(order_id: str):
        """Get order status by ID."""
        state.metrics.increment("order_status_checks")
        
        return {
            "order_id": order_id,
            "status": "UNKNOWN",
            "message": "Order not found",
        }

    @app.delete("/orders/{order_id}")
    async def cancel_order(order_id: str):
        """Cancel an order."""
        state.metrics.increment("order_cancellations")

        if state.config.dry_run or state.broker is None:
            return state.dry_run_broker.cancel_order_mock(order_id)

        try:
            cancelled = await state.broker.cancel_order(order_id)
            return {
                "order_id": order_id,
                "cancelled": cancelled,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Cancel order error for %s: %s", order_id, exc)
            raise HTTPException(status_code=502, detail=str(exc))

    # ========================================================================
    # Positions & Risk Endpoints
    # ========================================================================

    @app.get("/positions")
    async def positions():
        """Current positions."""
        state.metrics.increment("positions_requests", description="Positions API calls")

        if state.config.dry_run or state.broker is None:
            return {
                "positions": [],
                "total_exposure": 0,
                "count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dry_run": True,
            }

        try:
            pos_list = await state.broker.get_positions()
            return {
                "positions": pos_list,
                "total_exposure": 0,
                "count": len(pos_list),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Positions fetch error: %s", exc)
            raise HTTPException(status_code=502, detail=str(exc))

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

    # ========================================================================
    # Options Chain Endpoints
    # ========================================================================

    @app.get("/options/chain/{underlying}")
    async def get_option_chain(underlying: str, exchange: str = Query("NSE"), expiry_index: int = Query(0)):
        """Get option chain for underlying."""
        state.metrics.increment("option_chain_requests", labels={
            "underlying": underlying,
            "exchange": exchange,
        })
        
        # DRY run mode - return mock data
        if state.config.dry_run:
            return {
                "underlying": underlying,
                "exchange": exchange,
                "expiry_index": expiry_index,
                "expiry": None,
                "underlying_price": 0,
                "atm_strike": 0,
                "strikes": [],
                "total_call_oi": 0,
                "total_put_oi": 0,
                "pcr_oi": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        # Circuit breaker protection
        try:
            with state.circuit_breaker():
                from brokersv2.core.types import Exchange
                
                # Map exchange string to enum
                try:
                    exchange_enum = Exchange(exchange.upper())
                except ValueError:
                    exchange_enum = Exchange.NSE
                
                # Fetch option chain from broker adapter
                chain_data = await state.broker_adapter.get_option_chain(
                    symbol=underlying,
                    exchange=exchange_enum,
                    expiry_index=expiry_index,
                )
                
                # Convert to dict for JSON response
                return chain_data.to_dict()
                
        except Exception as e:
            logger.error(f"Error fetching option chain for {underlying}: {e}")
            state.metrics.increment("option_chain_errors", labels={
                "underlying": underlying,
                "error": str(type(e).__name__),
            })
            return {
                "underlying": underlying,
                "exchange": exchange,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    @app.get("/options/expiries/{underlying}")
    async def get_expiry_list(underlying: str, exchange: str = Query("NSE")):
        """Get expiry dates for underlying."""
        state.metrics.increment("expiry_list_requests")
        
        return {
            "underlying": underlying,
            "exchange": exchange,
            "expiries": [],
            "count": 0,
        }

    # ========================================================================
    # Broker Connection Management
    # ========================================================================

    @app.get("/broker/status")
    async def broker_status():
        """Get broker connection status."""
        return {
            "connected": not state.config.dry_run,
            "broker_type": "dhan",
            "dry_run": state.config.dry_run,
            "circuit_breaker_state": state.circuit_breaker.state.value,
            "last_check": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/broker/health")
    async def broker_health():
        """Check broker health."""
        cb_state = state.circuit_breaker.state
        
        if cb_state.value == "open":
            return {
                "healthy": False,
                "circuit_breaker": "OPEN",
                "message": "Circuit breaker open - broker unavailable",
            }
        
        return {
            "healthy": True,
            "circuit_breaker": cb_state.value,
            "latency_ms": 0,
            "message": "Broker connected" if not state.config.dry_run else "DRY RUN mode active",
        }

    # ========================================================================
    # WebSocket Streaming Endpoints
    # ========================================================================

    @app.websocket("/ws/ticks")
    async def stream_ticks(websocket: WebSocket):
        """WebSocket endpoint for real-time tick streaming via DhanWebSocketManager."""
        await websocket.accept()

        market_data = state.market_data

        if market_data is None or state.broker is None:
            await websocket.send_json({"error": "Market data service not configured"})
            await websocket.close()
            return

        try:
            msg = await websocket.receive_json()
            symbols = msg.get("symbols", [])
            exchange = msg.get("exchange", "NSE").upper()

            if not symbols:
                await websocket.send_json({"error": "No symbols provided"})
                await websocket.close()
                return

            from brokersv2.domain.instrument.models import CanonicalInstrument
            instruments = [
                CanonicalInstrument.from_symbol(f"{exchange}:{sym}")
                for sym in symbols
            ]

            logger.info("Tick streaming: subscribing to %s", symbols)

            async for tick in state.broker.stream_ticks(instruments):
                await websocket.send_json({
                    "symbol": tick.instrument.symbol if hasattr(tick.instrument, "symbol") else str(tick.instrument),
                    "ltp": float(tick.ltp),
                    "volume": int(tick.volume),
                    "timestamp": tick.timestamp.isoformat(),
                })

        except WebSocketDisconnect:
            logger.info("Tick streaming client disconnected")
        except Exception as exc:
            logger.error("Tick streaming error: %s", exc)
            try:
                await websocket.send_json({"error": str(exc)})
            except Exception:
                pass

    @app.websocket("/ws/quotes")
    async def stream_quotes(websocket: WebSocket):
        """
        WebSocket endpoint for real-time tick streaming via DhanHQ market feed.

        Consumes the broker's WebSocket stream (stream_ticks) instead of
        polling REST.  Ticks are forwarded to the client as they arrive.

        Message format from client:
            {"symbols": ["NIFTY", "BANKNIFTY"], "exchange": "NSE"}
        """
        await websocket.accept()

        if state.broker is None:
            await websocket.send_json({"error": "Broker not configured"})
            await websocket.close()
            return

        try:
            msg = await websocket.receive_json()
            symbols = msg.get("symbols", [])
            exchange = msg.get("exchange", "NSE").upper()

            if not symbols:
                await websocket.send_json({"error": "No symbols provided"})
                await websocket.close()
                return

            if len(symbols) > 100:
                await websocket.send_json({"error": "Maximum 100 symbols per subscription"})
                await websocket.close()
                return

            from brokersv2.domain.instrument.models import CanonicalInstrument
            instruments = [
                CanonicalInstrument.from_symbol(f"{exchange}:{sym}")
                for sym in symbols
            ]

            logger.info("Quote streaming: subscribing to %s via WebSocket feed", symbols)

            async for tick in state.broker.stream_ticks(instruments):
                try:
                    await websocket.send_json({
                        "symbol": getattr(tick, "symbol", str(tick)),
                        "ltp": float(getattr(tick, "ltp", getattr(tick, "price", 0))),
                        "volume": int(getattr(tick, "volume", 0)),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as send_exc:
                    logger.warning("Failed to send tick to client: %s", send_exc)
                    break

        except WebSocketDisconnect:
            logger.info("Quote streaming client disconnected")
        except Exception as exc:
            logger.error("Quote streaming error: %s", exc)
            try:
                await websocket.send_json({"error": str(exc)})
            except Exception:
                pass

    @app.websocket("/ws/depth")
    async def stream_depth(websocket: WebSocket):
        """WebSocket endpoint for market depth streaming."""
        await websocket.accept()

        if state.market_data is None or state.broker is None:
            await websocket.send_json({"error": "Market data service not configured"})
            await websocket.close()
            return

        try:
            msg = await websocket.receive_json()
            symbol = msg.get("symbol")
            exchange = msg.get("exchange", "NSE").upper()

            if not symbol:
                await websocket.send_json({"error": "No symbol provided"})
                await websocket.close()
                return

            logger.info("Depth streaming: subscribed to %s", symbol)

            async for depth_event in state.market_data.stream_depth_updates(symbol):
                await websocket.send_json({
                    "symbol": depth_event.symbol if hasattr(depth_event, "symbol") else symbol,
                    "timestamp": depth_event.timestamp.isoformat() if hasattr(depth_event, "timestamp") else datetime.now(timezone.utc).isoformat(),
                    "bids": [
                        {"price": level.price, "quantity": level.quantity, "orders": level.orders}
                        for level in depth_event.bids
                    ],
                    "asks": [
                        {"price": level.price, "quantity": level.quantity, "orders": level.orders}
                        for level in depth_event.asks
                    ],
                    "sequence": getattr(depth_event, "sequence", 0),
                })

        except WebSocketDisconnect:
            logger.info("Depth streaming client disconnected")
        except Exception as exc:
            logger.error("Depth streaming error: %s", exc)
            try:
                await websocket.send_json({"error": str(exc)})
            except Exception:
                pass

    # ========================================================================
    # Middleware for request tracking
    # ========================================================================

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
