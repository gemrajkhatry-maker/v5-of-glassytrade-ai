"""
Application bootstrap — single composition root for all entry points.

All services, adapters, and infrastructure components are wired here.
Entry points (CLI, Gateway, workers) must call these factories rather than
constructing infrastructure classes directly.

No sys.path manipulation.  No legacy broker_factory imports.
Credentials are read from environment variables only (auto-loaded from .env
via python-dotenv if available).

Public API:
    adapter = create_dhan_adapter(dry_run=False)
    market_data = create_market_data_service(adapter)
    order_mgr   = create_order_manager(adapter)
    app         = create_gateway_app(config)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from brokersv2.core.constants import API, CircuitBreaker, Gateway

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env() -> None:
    """Load .env from the project root (if python-dotenv is available)."""
    try:
        from dotenv import load_dotenv
        cwd = Path.cwd()
        for directory in [cwd, *cwd.parents]:
            env_file = directory / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=False)
                logger.debug("Loaded environment from %s", env_file)
                return
    except ImportError:
        pass  # python-dotenv not installed; rely on system environment.


def _require_env(name: str) -> str:
    """Return the value of an environment variable or raise ValueError."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"Required environment variable '{name}' is not set. "
            f"Set it in your .env file or shell environment."
        )
    return value


# ---------------------------------------------------------------------------
# create_dhan_gateway  (CLI entry point — high-level, string-based API)
# ---------------------------------------------------------------------------

def create_dhan_gateway():
    """
    Build and return a DhanGateway for CLI use.

    DhanGateway provides a symbol-string-based API that matches the CLI's
    existing call patterns (historical/option_chain/get_quote).
    It is backed by the same DhanHttpClient as DhanBrokerAdapter.

    Returns:
        DhanGateway instance.  Methods are async; CLI callers must await them.
    """
    _load_env()

    from brokersv2.infrastructure.dhan_adapter.factory import DhanGateway

    gateway = DhanGateway.from_env()
    logger.info("DhanGateway created for CLI use")
    return gateway


# ---------------------------------------------------------------------------
# create_dhan_adapter
# ---------------------------------------------------------------------------

def create_dhan_adapter(dry_run: bool = False):
    """
    Build and return a fully configured DhanBrokerAdapter.

    Reads DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN from the environment.
    Wires BrokerRateLimiter and CircuitBreaker automatically.

    Args:
        dry_run: When True the adapter logs but never sends real orders.

    Returns:
        DhanBrokerAdapter instance implementing IBrokerAdapter.
    """
    _load_env()

    client_id = _require_env("DHAN_CLIENT_ID")
    access_token = _require_env("DHAN_ACCESS_TOKEN")

    from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
    from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
    from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter
    from brokersv2.resilience.policies.rate_limit import BrokerRateLimiter
    from brokersv2.core.resilience import CircuitBreaker

    config = DhanConfig(
        client_id=client_id,
        access_token=access_token,
        base_url=os.environ.get("DHAN_BASE_URL", API.DHAN_BASE_URL),
        ws_url=os.environ.get("DHAN_WS_URL", API.DHAN_WS_URL),
        timeout=int(os.environ.get("DHAN_TIMEOUT", str(API.DEFAULT_TIMEOUT))),
    )

    rate_limiter = BrokerRateLimiter()
    circuit_breaker = CircuitBreaker(
        failure_threshold=CircuitBreaker.FAILURE_THRESHOLD,
        recovery_timeout=CircuitBreaker.RECOVERY_TIMEOUT,
    )
    mapper = InstrumentMapper()

    adapter = DhanBrokerAdapter(
        config=config,
        mapper=mapper,
        rate_limiter=rate_limiter,
        circuit_breaker=circuit_breaker,
        dry_run=dry_run,
        auth_provider=None,  # Auth provider wired separately for CLI path
    )

    # Wire auth provider for token lifecycle (bootstrap path)
    if not dry_run:
        try:
            from brokersv2.infrastructure.dhan_adapter.auth_provider import DhanAuthProvider
            auth_provider = DhanAuthProvider(client_id=client_id)
            auth_provider.set_current_token(access_token)
            adapter._auth_provider = auth_provider
            adapter._client._auth_provider = auth_provider
        except Exception as exc:
            logger.warning("DhanAuthProvider could not be wired: %s", exc)

    # Wire margin checker into the HTTP client (after client is constructed)
    if not dry_run:
        try:
            from brokersv2.oms.margin_checker import MarginChecker
            adapter.client._margin_checker = MarginChecker(adapter.client)
        except Exception as exc:
            logger.warning("MarginChecker could not be wired: %s", exc)

    logger.info(
        "DhanBrokerAdapter created (client_id=...%s, dry_run=%s)",
        client_id[-4:],
        dry_run,
    )
    return adapter


# ---------------------------------------------------------------------------
# create_market_data_service
# ---------------------------------------------------------------------------

def create_market_data_service(adapter=None):
    """
    Build and return a MarketDataService wired to real providers.

    Uses DhanWebSocketManager for live streaming and HistoricalDataRouter
    with Dhan (primary) + OpenChart (fallback) for historical data.

    Args:
        adapter: Optional pre-built DhanBrokerAdapter.  If None a new one is
                 created from the environment.

    Returns:
        MarketDataService instance.
    """
    if adapter is None:
        adapter = create_dhan_adapter()

    from brokersv2.providers.dhan_provider import DhanHistoricalProvider
    from brokersv2.providers.opencart_provider import OpenChartHistoricalProvider
    from brokersv2.providers.router import HistoricalDataRouter
    from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
    from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
    from brokersv2.infrastructure.dhan_adapter.websocket import DhanWebSocketManager
    from brokersv2.marketdata.service import MarketDataService

    # Historical providers
    dhan_provider = DhanHistoricalProvider(adapter=adapter)
    openchart_provider = OpenChartHistoricalProvider()
    historical_router = HistoricalDataRouter(
        primary=dhan_provider,
        fallback=openchart_provider,
    )

    # Live WebSocket manager (uses the real DhanHQ SDK)
    ws_manager = DhanWebSocketManager(
        config=adapter._config,
        mapper=adapter._mapper,
    )

    service = MarketDataService(
        historical_router=historical_router,
        ws_manager=ws_manager,
    )

    logger.info("MarketDataService created")
    return service


# ---------------------------------------------------------------------------
# create_order_manager
# ---------------------------------------------------------------------------

def create_order_manager(adapter=None):
    """
    Build and return an OrderManager wired to the provided adapter.

    Args:
        adapter: Optional pre-built DhanBrokerAdapter.

    Returns:
        (OrderManager, EventBus) tuple — EventBus is needed by the caller to
        subscribe downstream handlers.
    """
    if adapter is None:
        adapter = create_dhan_adapter()

    from brokersv2.events.bus import EventBus
    from brokersv2.risk.gateway import RiskGateway
    from brokersv2.oms.order_manager import OrderManager

    event_bus = EventBus()
    risk = RiskGateway()
    order_manager = OrderManager(
        broker=adapter,
        risk=risk,
        event_bus=event_bus,
    )

    logger.info("OrderManager created")
    return order_manager, event_bus


# ---------------------------------------------------------------------------
# create_gateway_app
# ---------------------------------------------------------------------------

def create_gateway_app(config=None, dry_run: Optional[bool] = None):
    """
    Build and return a fully wired FastAPI application.

    Services are stored in app.state so endpoints can access them via
    request.app.state.broker / .market_data / .order_manager.

    Args:
        config: Optional GatewayConfig.  Defaults are used if None.
        dry_run: Override dry_run flag.  Reads GATEWAY_DRY_RUN env var if None.

    Returns:
        Configured FastAPI application instance.
    """
    from brokersv2.gateway.server import GatewayConfig, create_app

    if config is None:
        _load_env()
        _dry_run = dry_run
        if _dry_run is None:
            _dry_run = os.environ.get("GATEWAY_DRY_RUN", str(Gateway.DEFAULT_DRY_RUN)).lower() == "true"
        config = GatewayConfig(
            host=os.environ.get("GATEWAY_HOST", Gateway.DEFAULT_HOST),
            port=int(os.environ.get("GATEWAY_PORT", str(Gateway.DEFAULT_PORT))),
            debug=os.environ.get("GATEWAY_DEBUG", str(Gateway.DEFAULT_DEBUG)).lower() == "true",
            dry_run=_dry_run,
        )
    else:
        _dry_run = config.dry_run

    adapter = create_dhan_adapter(dry_run=_dry_run)
    market_data = create_market_data_service(adapter)
    order_manager, event_bus = create_order_manager(adapter)

    app = create_app(config)
    app.state.broker = adapter
    app.state.market_data = market_data
    app.state.order_manager = order_manager
    app.state.event_bus = event_bus

    # Wire shared market hours gate (prevents per-request instantiation drift)
    from brokersv2.domain.market.hours import MarketHoursGate
    app.state.market_hours_gate = MarketHoursGate(bypass=_dry_run)

    # Background tasks registered on the FastAPI lifespan
    _register_lifespan_tasks(app, adapter)

    logger.info("Gateway application created (dry_run=%s)", _dry_run)
    return app


def _register_lifespan_tasks(app, adapter) -> None:
    """
    Register startup coroutines on ``app.state._startup_tasks``.

    The gateway's lifespan context manager (server.py) iterates this list
    during startup — no deprecated @on_event decorator needed.

    Tasks registered here:
        1. PositionReconciler  — seed position book from broker on startup
        2. AutoSquareOffScheduler — fire at 15:20 IST for INTRADAY positions
        3. MasterDataLoader.schedule_daily_refresh — refresh CSV at 08:45 IST
    """
    if not hasattr(app.state, "_startup_tasks"):
        app.state._startup_tasks = []

    async def _run_startup(app):
        import asyncio as _asyncio

        # 1. Position reconciliation
        try:
            from brokersv2.oms.position_reconciler import PositionReconciler
            reconciler = PositionReconciler(adapter.client)
            book = await reconciler.reconcile()
            app.state.position_book = book
        except Exception as exc:
            logger.error("Position reconciliation failed (startup): %s", exc)
            from brokersv2.oms.position_reconciler import PositionBook
            app.state.position_book = PositionBook()

        # 2. Auto-square-off background task — returned as coroutine for lifespan to schedule
        async def _aso_loop():
            try:
                from brokersv2.oms.auto_square_off import AutoSquareOffScheduler
                aso = AutoSquareOffScheduler()
                await aso.run(adapter, app.state.position_book, adapter._mapper)
            except Exception as exc:
                logger.error("AutoSquareOffScheduler crashed: %s", exc)

        _asyncio.ensure_future(_aso_loop())

        # 3. Instrument master daily refresh
        async def _master_refresh_loop():
            try:
                from brokersv2.domain.instrument.master_loader import MasterDataLoader
                loader = MasterDataLoader()
                await loader.schedule_daily_refresh()
            except Exception as exc:
                logger.warning("MasterDataLoader daily refresh crashed: %s", exc)

        _asyncio.ensure_future(_master_refresh_loop())

        # 4. Token refresh scheduler — keeps auth token alive
        try:
            from brokersv2.infrastructure.dhan_adapter.token_refresh_scheduler import TokenRefreshScheduler
            auth = getattr(adapter, '_auth_provider', None)
            if auth is not None:
                scheduler = TokenRefreshScheduler(auth, adapter._client)
                _asyncio.ensure_future(scheduler.start())
                logger.info("TokenRefreshScheduler started")
        except Exception as exc:
            logger.warning("TokenRefreshScheduler could not be started: %s", exc)

    app.state._startup_tasks.append(_run_startup)
