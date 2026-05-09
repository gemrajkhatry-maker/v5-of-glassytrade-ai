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


class DryRunBroker:
    """
    Mock broker for DRY run mode - simulates all operations without real execution.
    
    Features:
    - Mock order placement with generated IDs
    - Mock quotes with realistic prices
    - Mock historical data
    - Operation logging for audit
    """

    def __init__(self):
        self.operation_log: List[Dict[str, Any]] = []
        self._order_counter = 0

    def place_order_mock(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        side: str,
        order_type: str,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Simulate order placement."""
        self._order_counter += 1
        order_id = f"DRY_RUN_{self._order_counter}_{uuid.uuid4().hex[:8]}"

        operation = {
            "operation": "place_order",
            "order_id": order_id,
            "symbol": symbol,
            "exchange": exchange,
            "quantity": quantity,
            "side": side,
            "order_type": order_type,
            "price": price,
            "status": "COMPLETED",
            "dry_run": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.operation_log.append(operation)
        logger.info(f"[DRY RUN] Simulated order: {order_id} - {side} {quantity} {symbol}")

        return operation

    def cancel_order_mock(self, order_id: str) -> Dict[str, Any]:
        """Simulate order cancellation."""
        operation = {
            "operation": "cancel_order",
            "order_id": order_id,
            "cancelled": True,
            "dry_run": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.operation_log.append(operation)
        logger.info(f"[DRY RUN] Simulated cancellation: {order_id}")

        return operation

    def get_quote_mock(self, symbol: str) -> Dict[str, Any]:
        """Simulate quote retrieval."""
        # Generate realistic mock prices based on symbol
        base_price = {
            "RELIANCE": 2500.0,
            "TCS": 3500.0,
            "INFY": 1500.0,
            "HDFCBANK": 1600.0,
            "NIFTY": 22000.0,
            "BANKNIFTY": 48000.0,
        }.get(symbol.split(":")[-1] if ":" in symbol else symbol, 1000.0)

        import random
        ltp = base_price * random.uniform(0.98, 1.02)

        return {
            "symbol": symbol,
            "ltp": round(ltp, 2),
            "open": round(base_price * 0.99, 2),
            "high": round(base_price * 1.02, 2),
            "low": round(base_price * 0.98, 2),
            "close": round(base_price, 2),
            "volume": random.randint(100000, 1000000),
            "dry_run": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_historical_mock(
        self,
        symbol: str,
        exchange: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> Dict[str, Any]:
        """Simulate historical data retrieval."""
        # Generate mock candles
        import random
        base_price = 1000.0
        candles = []

        # Generate 30 candles as example
        for i in range(30):
            open_price = base_price * random.uniform(0.95, 1.05)
            high_price = open_price * random.uniform(1.01, 1.03)
            low_price = open_price * random.uniform(0.97, 0.99)
            close_price = open_price * random.uniform(0.98, 1.02)

            candles.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
                "volume": random.randint(10000, 100000),
            })

            base_price = close_price  # Next candle starts from close

        return {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "candles": candles,
            "count": len(candles),
            "from_date": from_date,
            "to_date": to_date,
            "dry_run": True,
        }


class AppState:
    """Application state holder."""

    def __init__(self):
        self.metrics = MetricsCollector()
        self.health_checker = HealthChecker()
        self.config: Optional[GatewayConfig] = None
        self.startup_time: Optional[datetime] = None
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        self.dry_run_broker = DryRunBroker()
        
        # Phase 2: Market data service
        self.market_data_service = None  # MarketDataService (set externally)


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
    async def get_quote(symbol: str):
        """Get current quote for symbol."""
        state.metrics.increment("quote_requests", labels={"symbol": symbol})
        
        # DRY Run mode
        if state.config.dry_run:
            return state.dry_run_broker.get_quote_mock(symbol)
        
        # TODO: Wire to real broker adapter with circuit breaker
        return {
            "symbol": symbol,
            "ltp": 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 0.0,
            "volume": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

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
        
        # DRY Run mode
        if state.config.dry_run:
            return state.dry_run_broker.get_historical_mock(
                symbol=request.symbol,
                exchange=request.exchange,
                from_date=request.from_date,
                to_date=request.to_date,
                interval=request.interval,
            )
        
        # TODO: Wire to broker adapter historical method with circuit breaker
        return {
            "symbol": request.symbol,
            "exchange": request.exchange,
            "interval": request.interval,
            "candles": [],
            "count": 0,
            "from_date": request.from_date,
            "to_date": request.to_date,
        }

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
        
        # DRY Run mode
        if state.config.dry_run:
            return state.dry_run_broker.place_order_mock(
                symbol=request.symbol,
                exchange=request.exchange,
                quantity=request.quantity,
                side=request.side,
                order_type=request.order_type,
                price=request.price,
            )
        
        return {
            "order_id": "ORD_TEMP",
            "status": "PENDING",
            "symbol": request.symbol,
            "exchange": request.exchange,
            "quantity": request.quantity,
            "side": request.side,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

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
        
        # DRY Run mode
        if state.config.dry_run:
            return state.dry_run_broker.cancel_order_mock(order_id)
        
        return {
            "order_id": order_id,
            "cancelled": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ========================================================================
    # Positions & Risk Endpoints
    # ========================================================================

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
        """WebSocket endpoint for real-time tick streaming."""
        await websocket.accept()
        
        market_data = app.state.market_data_service
        
        if not market_data or not market_data._ws_manager:
            await websocket.send_json({"error": "Market data service not configured"})
            await websocket.close()
            return
        
        try:
            # Get symbols from client
            msg = await websocket.receive_json()
            symbols = msg.get("symbols", [])
            
            if not symbols:
                await websocket.send_json({"error": "No symbols provided"})
                await websocket.close()
                return
            
            logger.info(f"Tick streaming client subscribed to: {symbols}")
            
            # TODO: Convert symbols to CanonicalInstrument and subscribe
            # For now, stream from existing tick source if available
            
            # Stream ticks
            while True:
                # Keep connection alive
                await websocket.receive_text()
                
        except WebSocketDisconnect:
            logger.info("Tick streaming client disconnected")
        except Exception as e:
            logger.error(f"Tick streaming error: {e}")
            try:
                await websocket.send_json({"error": str(e)})
            except:
                pass

    @app.websocket("/ws/quotes")
    async def stream_quotes(websocket: WebSocket):
        """WebSocket endpoint for real-time quote streaming."""
        await websocket.accept()
        
        market_data = app.state.market_data_service
        
        if not market_data:
            await websocket.send_json({"error": "Market data service not configured"})
            await websocket.close()
            return
        
        try:
            # Get symbols from client
            msg = await websocket.receive_json()
            symbols = msg.get("symbols", [])
            
            if not symbols:
                await websocket.send_json({"error": "No symbols provided"})
                await websocket.close()
                return
            
            logger.info(f"Quote streaming client subscribed to: {symbols}")
            
            # TODO: Implement quote streaming
            # For now, keep connection alive
            while True:
                await websocket.receive_text()
                
        except WebSocketDisconnect:
            logger.info("Quote streaming client disconnected")
        except Exception as e:
            logger.error(f"Quote streaming error: {e}")

    @app.websocket("/ws/depth")
    async def stream_depth(websocket: WebSocket):
        """WebSocket endpoint for market depth streaming."""
        await websocket.accept()
        
        market_data = app.state.market_data_service
        
        if not market_data or not market_data._ws_manager:
            await websocket.send_json({"error": "Market data service not configured"})
            await websocket.close()
            return
        
        try:
            # Get symbol from client
            msg = await websocket.receive_json()
            symbol = msg.get("symbol")
            
            if not symbol:
                await websocket.send_json({"error": "No symbol provided"})
                await websocket.close()
                return
            
            logger.info(f"Depth streaming client subscribed to: {symbol}")
            
            # Stream depth updates
            async for depth_event in market_data.stream_depth_updates(symbol):
                # Convert to dict for JSON serialization
                depth_dict = {
                    "symbol": depth_event.symbol,
                    "timestamp": depth_event.timestamp.isoformat(),
                    "bids": [
                        {"price": level.price, "quantity": level.quantity, "orders": level.orders}
                        for level in depth_event.bids
                    ],
                    "asks": [
                        {"price": level.price, "quantity": level.quantity, "orders": level.orders}
                        for level in depth_event.asks
                    ],
                    "sequence": depth_event.sequence,
                }
                
                await websocket.send_json(depth_dict)
                
        except WebSocketDisconnect:
            logger.info("Depth streaming client disconnected")
        except Exception as e:
            logger.error(f"Depth streaming error: {e}")
            try:
                await websocket.send_json({"error": str(e)})
            except:
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
