"""
Dhan Application Broker - Facade delegating to focused services.

DhanBroker implements IBrokerPort as a thin facade. All business logic
lives in the service modules under ``services/``.

Example:
    >>> from brokers.broker.dhan.application import DhanBroker, DhanConfig
    >>>
    >>> broker = DhanBroker.create(
    ...     client_id="your_client_id",
    ...     access_token="your_access_token",
    ... )
    >>>
    >>> async with broker:
    ...     quote = broker.get_quote(instrument)
    ...     async for tick in broker.stream_ticker([instrument]):
    ...         print(tick.price)
"""

import asyncio
import threading
from datetime import datetime
from typing import (
    List,
    Dict,
    Optional,
    AsyncIterator,
    Any,
)

import pandas as pd

from brokers.broker.ports import IBrokerPort
from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OptionChain,
    MarketDepth,
    BulkHistoricalResult,
)
from brokers.broker.types import Exchange

from brokers.broker.dhan.ports import (
    IHttpClient,
    IWebSocketClient,
    ISymbolMapper,
    IAuthProvider,
    IRateLimiter,
    ICircuitBreaker,
)
from brokers.broker.dhan.domain import (
    DhanInstrument,
    DhanSymbolNotFoundError,
)
from brokers.broker.dhan.domain.constants import INDEX_UNDERLYINGS

from .exchange_resolver import DhanExchangeResolver, ResolvedExchange
from brokers.broker.logging import get_logger
from .config import DhanConfig
from .services import (
    MarketDataService,
    HistoricalService,
    StreamingService,
    OptionsService,
    OrderService,
    PortfolioService,
)

logger = get_logger("dhan.broker")


class DhanBroker(IBrokerPort):
    """
    Dhan broker facade — delegates to focused service modules.

    Implements IBrokerPort. Each method group is handled by a dedicated
    service (MarketDataService, HistoricalService, etc.) following SRP.

    Example:
        >>> broker = DhanBroker.create(client_id="...", access_token="...")
        >>> async with broker:
        ...     quote = broker.get_quote(instrument)
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(
        self,
        config: DhanConfig,
        http_client: Optional[IHttpClient] = None,
        ws_client: Optional[IWebSocketClient] = None,
        symbol_mapper: Optional[ISymbolMapper] = None,
        auth_provider: Optional[IAuthProvider] = None,
        rate_limiter: Optional[IRateLimiter] = None,
        circuit_breaker: Optional[ICircuitBreaker] = None,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._ws_client = ws_client
        self._symbol_mapper = symbol_mapper
        self._auth_provider = auth_provider
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker

        # Internal state
        self._initialized = False
        self._closed = False
        self._loop_lock = threading.Lock()  # Instance-level lock for event loop creation
        self._loop = None
        self._loop_thread = None
        self._instrument_cache: Dict[str, DhanInstrument] = {}
        self._option_symbol_cache: Dict[str, str] = {}

        # Create service instances (share deps via base class constructor)
        svc_kwargs = dict(
            config=config,
            http_client=http_client,
            symbol_mapper=symbol_mapper,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
            option_symbol_cache=self._option_symbol_cache,
            ensure_initialized=self._ensure_initialized,
        )
        self._market_data = MarketDataService(**svc_kwargs)
        self._historical = HistoricalService(**svc_kwargs)
        self._streaming = StreamingService(**svc_kwargs)
        self._options = OptionsService(**svc_kwargs)
        self._orders = OrderService(**svc_kwargs)
        self._portfolio = PortfolioService(**svc_kwargs)

        logger.debug(f"DhanBroker initialized with config: {config!r}")

    @classmethod
    def create(
        cls, client_id: str = None, access_token: str = None, **kwargs
    ) -> "DhanBroker":
        """
        Factory method to create broker with default components.

        Credentials can be provided or read from environment variables:
        - DHAN_CLIENT_ID
        - DHAN_ACCESS_TOKEN
        - DHAN_TOTP_SECRET / TOTP_SECRET
        - DHAN_PIN / PIN
        """
        # Always start from env config to pick up totp_secret, pin, etc.
        try:
            env_config = DhanConfig.from_env()
        except ValueError:
            env_config = None

        if not client_id:
            client_id = env_config.client_id if env_config else None
        if not access_token:
            access_token = env_config.access_token if env_config else None

        if not client_id:
            raise ValueError(
                "Dhan client_id not provided. Pass client_id or set DHAN_CLIENT_ID."
            )

        # Build config: merge env defaults with explicit overrides
        config_kwargs = {}
        if env_config:
            config_kwargs["totp_secret"] = env_config.totp_secret
            config_kwargs["pin"] = env_config.pin
        config_kwargs.update(kwargs)

        # Allow empty access_token — auth provider will handle it
        config = DhanConfig(
            client_id=client_id,
            access_token=access_token or "",
            **config_kwargs,
        )

        # -----------------------------------------------------------------
        # Token management: ensure valid token BEFORE building clients
        # Flow: valid token → reuse | near-expiry → renew | expired/empty → generate
        # -----------------------------------------------------------------
        from brokers.broker.dhan.infrastructure.auth_provider import DhanAuthProvider
        auth_provider = DhanAuthProvider(http_client=None)  # no HTTP client yet

        if config.totp_secret:
            auth_provider.set_totp_secret(config.totp_secret)
        if config.pin:
            auth_provider.set_pin(config.pin)

        if config.access_token:
            auth_provider.set_token(
                access_token=config.access_token,
                client_id=config.client_id,
            )

        # Only run token flow if token is missing or expired
        valid_token = config.access_token
        if not valid_token or auth_provider.is_expired:
            valid_token = auth_provider.ensure_valid_token_sync(client_id=client_id)
        else:
            logger.info("Existing token is valid, skipping auth flow")

        # Rebuild config with the valid token
        if valid_token != config.access_token:
            config = config.with_access_token(valid_token)
            logger.info("Token refreshed/generated during broker creation")

        # -----------------------------------------------------------------
        # Build infrastructure clients with valid token
        # -----------------------------------------------------------------
        from brokers.broker.dhan.infrastructure import (
            DhanHttpClient,
            DhanWebSocketClient,
            DhanSymbolMapper,
            TokenBucketRateLimiter,
        )

        http_client = DhanHttpClient(
            base_url=config.base_url,
            access_token=config.access_token,
            client_id=config.client_id,
            timeout=config.timeout,
        )

        ws_client = DhanWebSocketClient(
            ws_url=config.ws_url,
            access_token=config.access_token,
            client_id=config.client_id,
            auth_provider=None,  # set below
        )

        symbol_mapper = DhanSymbolMapper()
        rate_limiter = TokenBucketRateLimiter()

        from brokers.broker.dhan.infrastructure.resilience import DhanCircuitBreaker
        circuit_breaker = DhanCircuitBreaker()

        # Connect auth_provider to HTTP + WS clients for runtime refresh
        auth_provider._http = http_client
        http_client._auth_provider = auth_provider
        ws_client._auth_provider = auth_provider

        return cls(
            config=config,
            http_client=http_client,
            ws_client=ws_client,
            symbol_mapper=symbol_mapper,
            auth_provider=auth_provider,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def config(self) -> DhanConfig:
        return self._config

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_closed(self) -> bool:
        return self._closed

    # =========================================================================
    # Context Manager Protocol
    # =========================================================================

    async def __aenter__(self) -> "DhanBroker":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def initialize(self) -> None:
        """Initialize the broker and its components."""
        if self._initialized:
            return

        logger.info("Initializing DhanBroker...")

        try:
            if self._symbol_mapper:
                try:
                    await self._symbol_mapper.refresh_cache()
                except Exception as e:
                    logger.warning(
                        f"Symbol mapper cache refresh failed (non-critical): {e}"
                    )

            self._initialized = True
            logger.info("DhanBroker initialized successfully")

        except Exception:
            logger.exception("Failed to initialize DhanBroker")
            raise

    async def close(self) -> None:
        """Close the broker and release resources."""
        if self._closed:
            return

        logger.info("Closing DhanBroker...")

        if self._http_client:
            try:
                await self._http_client.close()
            except Exception as e:
                logger.warning(f"Error closing HTTP client: {e}")

        if self._ws_client:
            try:
                await self._ws_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting WebSocket: {e}")

        self._closed = True

        # Stop sidecar loop if it was created
        loop = getattr(self, "_loop", None)
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        loop_thread = getattr(self, "_loop_thread", None)
        if loop_thread is not None:
            loop_thread.join(timeout=5)

        logger.info("DhanBroker closed")

    def close_sync(self) -> None:
        """Close the broker synchronously."""
        if self._closed:
            return
        loop = getattr(self, "_loop", None)
        if loop and not loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(self.close(), loop)
            future.result(timeout=10)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread = getattr(self, "_loop_thread", None)
            if loop_thread:
                loop_thread.join(timeout=5)
        self._closed = True

    def __del__(self):
        """Best-effort cleanup on garbage collection."""
        if not getattr(self, "_closed", True):
            try:
                self.close_sync()
            except Exception:
                pass

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    def _run_async(self, coro, timeout: float = None):
        """Run an async coroutine from sync context using a persistent event loop.

        Thread-safe: only one sidecar loop is ever created, guarded by instance-level _loop_lock.

        Args:
            coro: Coroutine to run.
            timeout: Max seconds to wait for result. Defaults to HTTP timeout + 5s.

        Raises:
            DhanTimeoutError: If the coroutine exceeds the timeout.
        """
        self._ensure_loop()
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception:
            if hasattr(coro, "close"):
                coro.close()
            raise
        _timeout = timeout or (getattr(self._config, 'timeout', 30) + 5.0)
        try:
            return future.result(timeout=_timeout)
        except TimeoutError:
            future.cancel()
            from brokers.broker.dhan.domain.errors import DhanTimeoutError
            raise DhanTimeoutError(
                message=f"_run_async timed out after {_timeout}s",
                code="TIMEOUT",
                details={},
                timeout_seconds=_timeout,
            )

    def _ensure_loop(self):
        """Create the persistent sidecar event loop if not already running."""
        if hasattr(self, "_loop") and self._loop is not None and not self._loop.is_closed():
            return
        with self._loop_lock:
            # Double-check after acquiring lock
            if hasattr(self, "_loop") and self._loop is not None and not self._loop.is_closed():
                return
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop.run_forever,
                daemon=True,
                name="dhan-broker-loop",
            )
            self._loop_thread.start()

    # =========================================================================
    # Symbol Resolution (kept on facade — used by external callers)
    # =========================================================================

    _INDEX_UNDERLYINGS = INDEX_UNDERLYINGS

    @staticmethod
    def format_option_symbol(
        underlying: str, expiry: datetime, strike: float, option_type: str
    ) -> str:
        """Format a human-readable option symbol."""
        return OptionsService.format_option_symbol(underlying, expiry, strike, option_type)

    def detect_exchange(self, symbol: str) -> ResolvedExchange:
        """Auto-detect exchange from symbol name."""
        return DhanExchangeResolver.resolve(symbol)

    async def resolve_symbol(
        self, symbol: str, exchange: Optional[Exchange] = None
    ) -> DhanInstrument:
        """Resolve symbol to DhanInstrument with security ID."""
        cache_key = f"{symbol}_{exchange.value if exchange else 'auto'}"
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]

        resolved = DhanExchangeResolver.resolve(symbol, exchange)

        if self._symbol_mapper:
            security_id = await self._symbol_mapper.get_security_id(
                symbol, resolved.segment
            )

            if security_id:
                from brokers.broker.dhan.domain import InstrumentTypeEnum

                type_map = {
                    "index": InstrumentTypeEnum.INDEX,
                    "equity": InstrumentTypeEnum.EQUITY,
                    "index_option": InstrumentTypeEnum.INDEX_OPTION,
                    "stock_option": InstrumentTypeEnum.STOCK_OPTION,
                    "future": InstrumentTypeEnum.INDEX_FUTURE,
                    "commodity": InstrumentTypeEnum.COMMODITY_FUTURE,
                }
                instrument = DhanInstrument(
                    security_id=security_id,
                    trading_symbol=symbol,
                    symbol=symbol,
                    exchange_segment=resolved.segment,
                    instrument_type=type_map.get(resolved.symbol_type, InstrumentTypeEnum.EQUITY),
                )
                self._instrument_cache[cache_key] = instrument
                return instrument

        raise DhanSymbolNotFoundError(
            message=f"Cannot resolve symbol: {symbol}",
            details={"symbol": symbol, "exchange": str(exchange)},
        )

    # =========================================================================
    # Market Data — delegate to MarketDataService
    # =========================================================================

    def get_quote(self, instrument: Instrument) -> Quote:
        return self._run_async(self._market_data.get_quote_async(instrument))

    def get_quotes_batch(self, instruments: List[Instrument]) -> Dict[Instrument, Quote]:
        return self._run_async(self._market_data.get_quotes_batch_async(instruments))

    def get_quotes_by_segment(
        self, segment: str, sid_to_instrument: Dict[str, Instrument]
    ) -> Dict[Instrument, Quote]:
        return self._run_async(
            self._market_data.get_quotes_by_segment_async(segment, sid_to_instrument)
        )

    def get_ltp(self, instrument: Instrument) -> float:
        return self.get_quote(instrument).ltp

    def get_lot_size(self, symbol: str, exchange: Optional[Exchange] = None) -> int:
        """Get lot size for a symbol (sync)."""
        try:
            instrument = self._run_async(self.resolve_symbol(symbol, exchange))
            return instrument.lot_size
        except Exception as e:
            logger.warning(f"Failed to get lot size for {symbol}: {e}")
            return 1

    def get_exchange_config(self) -> "DhanExchangeConfig":
        """Get ExchangeConfig for RiskSizingEngine integration.
        
        Returns a config that fetches lot sizes from the broker's instrument cache.
        This ensures RiskSizingEngine uses accurate lot sizes.
        """
        return DhanExchangeConfig(self)

    async def get_quotes_batch_async(
        self, symbols: List[str], exchange: Optional[Exchange] = None
    ) -> Dict[str, Quote]:
        if not symbols:
            return {}
        instruments = [
            Instrument(symbol=sym, exchange=exchange or Exchange.NSE)
            for sym in symbols
        ]
        batch_result = await self._market_data.get_quotes_batch_async(instruments)
        return {inst.symbol: quote for inst, quote in batch_result.items()}

    async def get_ltp_batch_async(
        self, symbols: List[str], exchange: Optional[Exchange] = None
    ) -> Dict[str, float]:
        return await self._market_data.get_ltp_batch_async(symbols, exchange)

    # =========================================================================
    # Historical — delegate to HistoricalService
    # =========================================================================

    def get_historical(
        self,
        instrument: Instrument,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        include_oi: bool = False,
    ) -> pd.DataFrame:
        return self._run_async(
            self._historical.get_historical_async(
                instrument, from_date, to_date, interval, include_oi
            )
        )

    def bulk_historical(
        self,
        symbols: List[str],
        from_date: datetime,
        to_date: datetime,
        exchange: Exchange = Exchange.NSE,
        interval: str = "1d",
        continue_on_error: bool = True,
    ) -> BulkHistoricalResult:
        from brokers.broker.validation import OHLCValidator

        data: Dict[str, pd.DataFrame] = {}
        errors: Dict[str, str] = {}

        logger.info(f"Bulk historical download starting: {len(symbols)} symbols")

        for symbol in symbols:
            try:
                instrument = Instrument(symbol=symbol, exchange=exchange, security_id="")
                df = self.get_historical(
                    instrument=instrument,
                    from_date=from_date,
                    to_date=to_date,
                    interval=interval,
                )
                if not df.empty:
                    validation_errors = OHLCValidator.validate(df, symbol)
                    if validation_errors:
                        logger.warning(
                            f"Data validation warnings for {symbol}: {validation_errors}"
                        )

                data[symbol] = df
                logger.debug(f"Downloaded {symbol}: {len(df)} bars")

            except Exception as e:
                error_msg = str(e)
                errors[symbol] = error_msg
                logger.warning(f"Failed to download {symbol}: {error_msg}")
                if not continue_on_error:
                    break

        logger.info(
            f"Bulk historical download complete: {len(data)} successful, {len(errors)} failed"
        )
        return BulkHistoricalResult(data=data, errors=errors)

    async def get_historical_batch_async(
        self, requests: List[Dict[str, Any]], continue_on_error: bool = True
    ) -> Dict[str, pd.DataFrame]:
        await self._ensure_initialized()
        result: Dict[str, pd.DataFrame] = {}

        for req in requests:
            symbol = req.get("symbol")
            if not symbol:
                continue
            try:
                from_date = HistoricalService.parse_historical_date(req.get("from_date"))
                to_date = HistoricalService.parse_historical_date(req.get("to_date"))
                interval = req.get("interval", "1d")
                exchange = req.get("exchange")

                instrument = await self.resolve_symbol(symbol, exchange)

                df = await self._historical.get_historical_async(
                    Instrument(
                        symbol=symbol,
                        exchange=instrument.exchange_segment.to_exchange(),
                        security_id=instrument.security_id,
                    ),
                    from_date,
                    to_date,
                    interval,
                )
                result[symbol] = df

            except Exception as e:
                logger.warning(f"Failed to get historical for {symbol}: {e}")
                if not continue_on_error:
                    raise

        return result

    # =========================================================================
    # Streaming — delegate to StreamingService
    # =========================================================================

    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]:
        async for tick in self._streaming.stream_ticker(instruments):
            yield tick

    async def stream_quotes(self, instruments: List[Instrument]) -> AsyncIterator[Quote]:
        async for quote in self._streaming.stream_quotes(instruments):
            yield quote

    async def stream_depth(
        self, instruments: List[Instrument], depth_level: int = 20
    ) -> AsyncIterator[MarketDepth]:
        """Stream market depth. depth_level=20 (default), 200, or 5 (regular feed)."""
        async for depth in self._streaming.stream_depth(instruments, depth_level):
            yield depth

    async def stream_depth_20(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[MarketDepth]:
        """
        Stream 20-level market depth via the dedicated depth feed.

        Up to 50 NSE instruments per connection. Symbol names are backfilled
        from the instrument map using the standard security ID resolution flow.
        """
        async for depth in self._streaming.stream_depth_20(instruments):
            yield depth

    async def stream_depth_200(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[MarketDepth]:
        """
        Stream 200-level market depth via the full-depth feed.

        Only 1 instrument per connection (Dhan limit). If more than one
        instrument is passed, only the first is used.
        Symbol names are backfilled from the instrument map.
        """
        async for depth in self._streaming.stream_depth_200(instruments):
            yield depth

    async def stream_full(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[dict]:
        """Stream raw FULL packets for any exchange segment (including MCX).

        Use when stream_quotes() raises DhanFeedNotSupportedError for MCX.
        Each dict: ltp, open, high, low, close, volume, oi, atp,
        depth_bids, depth_asks, security_id, exchange_segment, symbol, timestamp.
        """
        async for pkt in self._streaming.stream_full(instruments):
            yield pkt

    # =========================================================================
    # Options — delegate to OptionsService
    # =========================================================================

    def get_option_chain(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain:
        return self._run_async(
            self._options.get_option_chain_async(underlying, exchange, expiry_index)
        )

    async def get_option_chain_async(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain:
        return await self._options.get_option_chain_async(underlying, exchange, expiry_index)

    def get_expiry_list(self, underlying: str, exchange: Exchange) -> List[datetime]:
        return self._run_async(
            self._options.get_expiry_list_async(underlying, exchange)
        )

    # =========================================================================
    # Orders — delegate to OrderService
    # =========================================================================

    def place_order(self, order: Order) -> Order:
        return self._run_async(self._orders.place_order_async(order))

    def cancel_order(self, order_id: str) -> bool:
        return self._run_async(self._orders.cancel_order_async(order_id))

    def get_order_status(self, order_id: str) -> Order:
        return self._run_async(self._orders.get_order_status_async(order_id))

    def get_orderbook(self) -> List[Order]:
        return self._run_async(self._orders.get_orderbook_async())

    # =========================================================================
    # Portfolio — delegate to PortfolioService
    # =========================================================================

    def get_positions(self) -> List[Position]:
        return self._run_async(self._portfolio.get_positions_async())

    async def get_trade_history_async(
        self, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None
    ) -> List[Any]:
        return await self._portfolio.get_trade_history_async(from_date, to_date)

    async def get_trade_book_async(self) -> List[Any]:
        return await self._portfolio.get_trade_book_async()

    async def get_pnl_async(
        self, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        return await self._portfolio.get_pnl_async(from_date, to_date)

    # =========================================================================
    # Async Compatibility Aliases
    # =========================================================================
    # These delegate to the service layer and preserve the internal async API
    # used by the backend adapters and tests.

    async def _get_quote_async(self, instrument: Instrument) -> Quote:
        return await self._market_data.get_quote_async(instrument)

    async def _get_quotes_batch_async(
        self, instruments: List[Instrument]
    ) -> Dict[Instrument, Quote]:
        return await self._market_data.get_quotes_batch_async(instruments)

    async def _get_historical_async(
        self, instrument: Instrument, from_date: datetime, to_date: datetime,
        interval: str, include_oi: bool = False,
    ) -> pd.DataFrame:
        return await self._historical.get_historical_async(
            instrument, from_date, to_date, interval, include_oi
        )

    async def get_historical_async(
        self, instrument: Instrument, from_date: datetime, to_date: datetime,
        interval: str = "1d", include_oi: bool = False,
    ) -> pd.DataFrame:
        """Fetch historical candles asynchronously.

        Public alias used by the trading engine's gap-fill callback
        (``TradingEngine.fetch_historical_callback``) for historical seeding.
        """
        return await self._get_historical_async(
            instrument, from_date, to_date, interval, include_oi
        )

    async def _place_order_async(self, order: Order) -> Order:
        return await self._orders.place_order_async(order)

    async def _cancel_order_async(self, order_id: str) -> bool:
        return await self._orders.cancel_order_async(order_id)

    async def _get_order_status_async(self, order_id: str) -> Order:
        return await self._orders.get_order_status_async(order_id)

    async def _get_positions_async(self) -> List[Position]:
        return await self._portfolio.get_positions_async()

    async def _get_orderbook_async(self) -> List[Order]:
        return await self._orders.get_orderbook_async()

    def _split_date_range(self, from_date, to_date, max_days):
        return self._historical._split_date_range(from_date, to_date, max_days)

    async def get_expired_options_historical_async(
        self,
        security_id: str,
        exchange: Exchange,
        instrument_type: str,
        expiry_code: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get historical data for expired option contracts."""
        await self._ensure_initialized()
        return await self._historical.get_expired_options_historical_async(
            security_id=security_id,
            exchange=exchange,
            instrument_type=instrument_type,
            expiry_code=expiry_code,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            strike=strike,
            option_type=option_type,
        )

    def get_expired_options_historical(
        self,
        security_id: str,
        exchange: Exchange,
        instrument_type: str,
        expiry_code: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get historical data for expired option contracts (sync wrapper)."""
        return self._run_async(
            self.get_expired_options_historical_async(
                security_id=security_id,
                exchange=exchange,
                instrument_type=instrument_type,
                expiry_code=expiry_code,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                strike=strike,
                option_type=option_type,
            )
        )

    # =========================================================================
    # String Representation
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"DhanBroker(config={self._config!r}, "
            f"initialized={self._initialized}, closed={self._closed})"
        )


class DhanExchangeConfig:
    """ExchangeConfig implementation using DhanBroker's instrument cache.
    
    This provides accurate lot sizes to RiskSizingEngine from the broker's
    official instrument data, ensuring positions are sized correctly.
    Implements ExchangeConfig protocol for drop-in compatibility.
    """
    
    def __init__(self, broker: "DhanBroker"):
        self._broker = broker
    
    def get_lot_size(self, symbol_or_underlying: str) -> int:
        """Get lot size from broker's instrument cache.
        
        Accepts symbol_or_underlying and normalizes it (matches ExchangeConfig protocol).
        """
        # Normalize symbol: "NIFTY 27 FEB 25500 CALL" -> "NIFTY"
        clean = (
            symbol_or_underlying.upper()
            .replace("NSE:", "")
            .replace("MCX:", "")
            .strip()
        )
        underlying = clean.split("-")[0].split(" ")[0]
        return self._broker.get_lot_size(underlying)
