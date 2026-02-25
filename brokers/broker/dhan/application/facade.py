"""
Dhan Facade - Simple unified API for common Dhan broker operations.

This module provides a facade class that simplifies common operations
with one-liner methods, auto-exchange detection, and auto-symbol resolution.

Features:
    - Auto-load credentials from environment
    - Auto-detect exchange from symbol name
    - Auto-resolve symbols to security IDs
    - One-liner methods for common operations
    - Batch operations for efficiency
    - Convenience methods for trading

Example:
    >>> from brokers.broker.dhan import DhanFacade
    >>> 
    >>> # Create facade (auto-loads from environment)
    >>> dhan = DhanFacade()
    >>> 
    >>> # One-liner historical data
    >>> df = dhan.historical("NIFTY", "2024-01-01", "2024-01-31")
    >>> 
    >>> # One-liner quote
    >>> quote = dhan.quote("RELIANCE")
    >>> 
    >>> # One-liner option chain
    >>> chain = dhan.option_chain("NIFTY")
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import (
    List,
    Dict,
    Optional,
    Any,
    Tuple,
    Union,
    TYPE_CHECKING,
)

import pandas as pd

from brokers.broker.logging import get_logger
from brokers.broker.entities import Instrument, Quote, Order, Position, OptionChain
from brokers.broker.types import Exchange, OrderSide

from brokers.broker.dhan.domain import (
    DhanInstrument,
    DhanQuote,
    DhanOption,
    DhanOptionChain,
    ExchangeSegment,
    DhanError,
    DhanSymbolNotFoundError,
    TRADES,
    PNL,
)

from .exchange_resolver import (
    DhanExchangeResolver,
    ResolvedExchange,
)

# Use TYPE_CHECKING to avoid circular import
if TYPE_CHECKING:
    from .broker import DhanBroker


# =============================================================================
# Logger
# =============================================================================

logger = get_logger("dhan.facade")


# =============================================================================
# Trade and P&L Data Classes
# =============================================================================

@dataclass
class Trade:
    """
    Represents a single trade execution.
    
    Attributes:
        trade_id: Unique trade ID.
        order_id: Associated order ID.
        symbol: Trading symbol.
        exchange: Exchange where trade occurred.
        side: BUY or SELL.
        quantity: Quantity traded.
        price: Execution price.
        timestamp: Trade timestamp.
        brokerage: Brokerage charged.
        taxes: Taxes charged.
    """
    trade_id: str
    order_id: str
    symbol: str
    exchange: Exchange
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime
    brokerage: float = 0.0
    taxes: float = 0.0
    
    @property
    def value(self) -> float:
        """Calculate trade value."""
        return self.quantity * self.price


@dataclass
class PnLReport:
    """
    P&L report for a period.
    
    Attributes:
        realized_pnl: Realized profit/loss.
        unrealized_pnl: Unrealized profit/loss.
        total_pnl: Total P&L.
        trades: List of trades.
        positions: List of positions.
    """
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    positions: List[Position] = field(default_factory=list)
    
    @property
    def trade_count(self) -> int:
        """Get number of trades."""
        return len(self.trades)


# =============================================================================
# DhanFacade Implementation
# =============================================================================

class DhanFacade:
    """
    Simple facade for common Dhan broker operations.
    
    This class provides a unified, easy-to-use API that wraps DhanBroker
    with one-liner methods, auto-exchange detection, and auto-symbol resolution.
    
    Features:
        - Auto-load credentials from environment
        - Auto-detect exchange from symbol name
        - Auto-resolve symbols to security IDs
        - One-liner methods for common operations
        - Batch operations for efficiency
    
    Attributes:
        _client_id: Dhan client ID.
        _access_token: Dhan access token.
        _totp_secret: Optional TOTP secret for auto-login.
        _broker: Lazy-initialized DhanBroker instance.
    
    Example:
        >>> # Create with environment variables
        >>> dhan = DhanFacade()
        >>> 
        >>> # Or with explicit credentials
        >>> dhan = DhanFacade(
        ...     client_id="your_client_id",
        ...     access_token="your_access_token"
        ... )
        >>> 
        >>> # One-liner operations
        >>> df = dhan.historical("NIFTY", "2024-01-01", "2024-01-31")
        >>> quote = dhan.quote("RELIANCE")
        >>> chain = dhan.option_chain("NIFTY")
    """
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        totp_secret: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize DhanFacade with credentials.
        
        Credentials are auto-loaded from environment if not provided:
        - DHAN_CLIENT_ID
        - DHAN_ACCESS_TOKEN
        - DHAN_TOTP_SECRET
        
        Args:
            client_id: Dhan client ID (optional, loads from env).
            access_token: Dhan access token (optional, loads from env).
            totp_secret: TOTP secret for auto-login (optional).
            **kwargs: Additional config options passed to DhanConfig.
        """
        self._client_id = client_id or os.getenv("DHAN_CLIENT_ID")
        self._access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")
        self._totp_secret = totp_secret or os.getenv("DHAN_TOTP_SECRET")
        self._config_kwargs = kwargs
        self._broker: Optional[DhanBroker] = None
        self._instrument_cache: Dict[str, DhanInstrument] = {}
        
        if not self._client_id or not self._access_token:
            raise ValueError(
                "Dhan credentials required. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN "
                "environment variables or pass client_id and access_token to constructor."
            )
        
        logger.debug("DhanFacade initialized")
    
    # =========================================================================
    # Broker Management
    # =========================================================================
    
    async def _get_broker(self) -> "DhanBroker":
        """
        Get or create the DhanBroker instance.
        
        Returns:
            DhanBroker instance.
        """
        if self._broker is None:
            # Import here to avoid circular import
            from .broker import DhanBroker
            self._broker = DhanBroker.create(
                client_id=self._client_id,
                access_token=self._access_token,
                **self._config_kwargs
            )
            await self._broker.initialize()
        return self._broker
    
    def _run_async(self, coro):
        """Run async coroutine in sync context using a persistent event loop.

        Uses a single long-lived loop so aiohttp sessions stay valid across calls,
        matching DhanBroker._run_async pattern.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()

        if not hasattr(self, "_loop") or self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)
    
    # =========================================================================
    # Exchange and Symbol Resolution
    # =========================================================================
    
    def detect_exchange(self, symbol: str) -> ResolvedExchange:
        """
        Auto-detect exchange from symbol name.
        
        Args:
            symbol: The symbol to detect exchange for.
        
        Returns:
            ResolvedExchange with exchange info.
        
        Example:
            >>> dhan.detect_exchange("NIFTY")
            ResolvedExchange(exchange=Exchange.NFO, segment=..., symbol_type='index')
        """
        return DhanExchangeResolver.resolve(symbol)
    
    async def resolve_symbol(
        self,
        symbol: str,
        exchange: Optional[Exchange] = None
    ) -> DhanInstrument:
        """
        Resolve symbol to DhanInstrument with security ID.
        
        Args:
            symbol: The symbol to resolve.
            exchange: Optional explicit exchange.
        
        Returns:
            DhanInstrument with security ID.
        
        Raises:
            DhanSymbolNotFoundError: If symbol cannot be resolved.
        
        Example:
            >>> inst = await dhan.resolve_symbol("NIFTY")
            >>> inst.security_id
            '12345'
        """
        # Check cache first
        cache_key = f"{symbol}_{exchange.value if exchange else 'auto'}"
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]
        
        # Resolve exchange if not provided
        resolved = DhanExchangeResolver.resolve(symbol, exchange)
        
        # Get broker and symbol mapper
        broker = await self._get_broker()
        
        if broker._symbol_mapper:
            security_id = await broker._symbol_mapper.get_security_id(
                symbol, resolved.segment
            )
            
            if security_id:
                instrument = DhanInstrument(
                    security_id=security_id,
                    trading_symbol=symbol,
                    symbol=symbol,
                    exchange_segment=resolved.segment,
                    instrument_type=broker._symbol_mapper._get_instrument_type(
                        resolved.segment, symbol
                    ),
                )
                self._instrument_cache[cache_key] = instrument
                return instrument
        
        raise DhanSymbolNotFoundError(
            message=f"Cannot resolve symbol: {symbol}",
            details={"symbol": symbol, "exchange": str(exchange)}
        )
    
    def resolve(self, symbol: str, exchange: Optional[Exchange] = None) -> DhanInstrument:
        """
        Synchronous version of resolve_symbol.
        
        Args:
            symbol: The symbol to resolve.
            exchange: Optional explicit exchange.
        
        Returns:
            DhanInstrument with security ID.
        """
        return self._run_async(self.resolve_symbol(symbol, exchange))
    
    # =========================================================================
    # Market Data - One-Liners
    # =========================================================================
    
    def quote(self, symbol: str, exchange: Optional[Exchange] = None) -> Quote:
        """
        Get current quote for symbol (one-liner).
        
        Args:
            symbol: The symbol to get quote for.
            exchange: Optional explicit exchange (auto-detected if not provided).
        
        Returns:
            Quote with current market data.
        
        Example:
            >>> q = dhan.quote("NIFTY")
            >>> print(q.ltp)
            18050.50
        """
        async def _get_quote():
            broker = await self._get_broker()
            resolved = DhanExchangeResolver.resolve(symbol, exchange)
            inst = Instrument(
                symbol=symbol,
                exchange=resolved.exchange,
                security_id="",
            )
            return broker.get_quote(inst)
        
        return self._run_async(_get_quote())
    
    def get_ltp(self, symbol: str, exchange: Optional[Exchange] = None) -> float:
        """
        Get last traded price (one-liner).
        
        Args:
            symbol: The symbol to get LTP for.
            exchange: Optional explicit exchange.
        
        Returns:
            Last traded price.
        
        Example:
            >>> ltp = dhan.get_ltp("RELIANCE")
            >>> print(ltp)
            2450.50
        """
        quote = self.quote(symbol, exchange)
        return quote.ltp
    
    def historical(
        self,
        symbol: str,
        from_date: Union[str, date, datetime],
        to_date: Union[str, date, datetime],
        interval: str = "1d",
        exchange: Optional[Exchange] = None
    ) -> pd.DataFrame:
        """
        Get historical OHLCV data (one-liner).
        
        Args:
            symbol: The symbol to get data for.
            from_date: Start date (str "YYYY-MM-DD", date, or datetime).
            to_date: End date (str "YYYY-MM-DD", date, or datetime).
            interval: Time interval ("1d", "5m", "15m", "1h", etc.).
            exchange: Optional explicit exchange.
        
        Returns:
            DataFrame with OHLCV data.
        
        Example:
            >>> df = dhan.historical("NIFTY", "2024-01-01", "2024-01-31")
            >>> print(df.head())
        """
        from_dt = self._parse_date(from_date)
        to_dt = self._parse_date(to_date)
        
        async def _get_historical():
            broker = await self._get_broker()
            resolved = DhanExchangeResolver.resolve(symbol, exchange)
            inst = Instrument(
                symbol=symbol,
                exchange=resolved.exchange,
                security_id="",
            )
            return broker.get_historical(inst, from_dt, to_dt, interval)
        
        return self._run_async(_get_historical())
    
    def _parse_date(self, date_val: Union[str, date, datetime]) -> datetime:
        """Parse date value to datetime."""
        if isinstance(date_val, datetime):
            return date_val
        elif isinstance(date_val, date):
            return datetime.combine(date_val, datetime.min.time())
        elif isinstance(date_val, str):
            return datetime.strptime(date_val, "%Y-%m-%d")
        else:
            raise ValueError(f"Invalid date format: {date_val}")
    
    # =========================================================================
    # Options - One-Liners
    # =========================================================================
    
    def option_chain(
        self,
        underlying: str,
        expiry_index: int = 0,
        exchange: Optional[Exchange] = None
    ) -> OptionChain:
        """
        Get option chain for underlying (one-liner).
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY").
            expiry_index: Which expiry (0=nearest, 1=next, etc.).
            exchange: Optional explicit exchange.
        
        Returns:
            OptionChain with calls and puts.
        
        Example:
            >>> chain = dhan.option_chain("NIFTY")
            >>> print(chain.spot_price)
            18000.0
        """
        async def _get_chain():
            broker = await self._get_broker()
            resolved = DhanExchangeResolver.resolve(underlying, exchange)
            return await broker.get_option_chain_async(
                underlying, resolved.exchange, expiry_index
            )
        
        return self._run_async(_get_chain())
    
    def get_expiry_list(
        self,
        underlying: str,
        exchange: Optional[Exchange] = None
    ) -> List[datetime]:
        """
        Get available expiry dates (one-liner).
        
        Args:
            underlying: Underlying symbol.
            exchange: Optional explicit exchange.
        
        Returns:
            List of expiry dates.
        
        Example:
            >>> expiries = dhan.get_expiry_list("NIFTY")
            >>> print(expiries[0])
            2024-02-22
        """
        async def _get_expiries():
            broker = await self._get_broker()
            resolved = DhanExchangeResolver.resolve(underlying, exchange)
            # Route through the OptionsService (public path — no private member access)
            return await broker._options_service.get_expiry_list_async(
                underlying, resolved.exchange
            )
        
        return self._run_async(_get_expiries())
    
    def find_atm_options(
        self,
        underlying: str,
        expiry_index: int = 0,
        exchange: Optional[Exchange] = None
    ) -> Tuple[Optional[DhanOption], Optional[DhanOption], float]:
        """
        Find ATM call and put options (one-liner).
        
        Args:
            underlying: Underlying symbol.
            expiry_index: Which expiry (0=nearest).
            exchange: Optional explicit exchange.
        
        Returns:
            Tuple of (call, put, spot_price).
        
        Example:
            >>> call, put, spot = dhan.find_atm_options("NIFTY")
            >>> print(f"ATM Strike: {call.strike if call else 'N/A'}")
        """
        chain = self.option_chain(underlying, expiry_index, exchange)
        
        # Convert to DhanOptionChain for convenience methods
        if isinstance(chain, OptionChain):
            # Build DhanOptionChain
            dhan_chain = self._to_dhan_option_chain(chain)
            return dhan_chain.get_atm()
        
        return (None, None, 0.0)
    
    def find_otm_options(
        self,
        underlying: str,
        distance: int = 1,
        expiry_index: int = 0,
        exchange: Optional[Exchange] = None
    ) -> Tuple[Optional[DhanOption], Optional[DhanOption]]:
        """
        Find OTM call and put options (one-liner).
        
        Args:
            underlying: Underlying symbol.
            distance: Number of strikes away from ATM.
            expiry_index: Which expiry.
            exchange: Optional explicit exchange.
        
        Returns:
            Tuple of (otm_call, otm_put).
        
        Example:
            >>> call, put = dhan.find_otm_options("NIFTY", distance=2)
        """
        chain = self.option_chain(underlying, expiry_index, exchange)
        
        if isinstance(chain, OptionChain):
            dhan_chain = self._to_dhan_option_chain(chain)
            return dhan_chain.get_otm(distance)
        
        return (None, None)
    
    def find_itm_options(
        self,
        underlying: str,
        distance: int = 1,
        expiry_index: int = 0,
        exchange: Optional[Exchange] = None
    ) -> Tuple[Optional[DhanOption], Optional[DhanOption]]:
        """
        Find ITM call and put options (one-liner).
        
        Args:
            underlying: Underlying symbol.
            distance: Number of strikes away from ATM.
            expiry_index: Which expiry.
            exchange: Optional explicit exchange.
        
        Returns:
            Tuple of (itm_call, itm_put).
        
        Example:
            >>> call, put = dhan.find_itm_options("NIFTY", distance=1)
        """
        chain = self.option_chain(underlying, expiry_index, exchange)
        
        if isinstance(chain, OptionChain):
            dhan_chain = self._to_dhan_option_chain(chain)
            return dhan_chain.get_itm(distance)
        
        return (None, None)
    
    def _to_dhan_option_chain(self, chain: OptionChain) -> DhanOptionChain:
        """Convert OptionChain to DhanOptionChain."""
        # Build strikes dictionary
        strikes: Dict[float, Tuple[DhanOption, DhanOption]] = {}
        
        for strike, inst in chain.calls.items():
            call_opt = DhanOption(
                strike=strike,
                option_type="CE",
                ltp=0.0,  # Would need quote data
                bid=0.0,
                ask=0.0,
                oi=0,
                volume=0,
                instrument=inst
            )
            put_inst = chain.puts.get(strike)
            put_opt = DhanOption(
                strike=strike,
                option_type="PE",
                ltp=0.0,
                bid=0.0,
                ask=0.0,
                oi=0,
                volume=0,
                instrument=put_inst
            ) if put_inst else None
            
            if put_opt:
                strikes[strike] = (call_opt, put_opt)
        
        return DhanOptionChain(
            underlying=chain.underlying.symbol if chain.underlying else "",
            expiry=chain.expiry.date() if chain.expiry else date.today(),
            spot_price=chain.spot_price,
            strikes=strikes
        )
    
    # =========================================================================
    # Batch Operations
    # =========================================================================
    
    def get_quotes_batch(
        self,
        symbols: List[str],
        exchange: Optional[Exchange] = None
    ) -> Dict[str, Quote]:
        """
        Get quotes for multiple symbols (batch operation).
        
        Args:
            symbols: List of symbols to get quotes for.
            exchange: Optional explicit exchange for all symbols.
        
        Returns:
            Dict mapping symbols to their quotes.
        
        Example:
            >>> quotes = dhan.get_quotes_batch(["NIFTY", "BANKNIFTY", "FINNIFTY"])
            >>> for sym, q in quotes.items():
            ...     print(f"{sym}: {q.ltp}")
        """
        async def _get_batch():
            broker = await self._get_broker()
            result: Dict[str, Quote] = {}
            
            for symbol in symbols:
                try:
                    instrument = await self.resolve_symbol(symbol, exchange)
                    quote = await broker._get_quote_async(
                        Instrument(
                            symbol=symbol,
                            exchange=instrument.exchange_segment.to_exchange(),
                            security_id=instrument.security_id
                        )
                    )
                    result[symbol] = quote
                except Exception as e:
                    logger.warning(f"Failed to get quote for {symbol}: {e}")
            
            return result
        
        return self._run_async(_get_batch())
    
    def get_ltp_batch(
        self,
        symbols: List[str],
        exchange: Optional[Exchange] = None
    ) -> Dict[str, float]:
        """
        Get LTP for multiple symbols (batch operation).
        
        Args:
            symbols: List of symbols to get LTP for.
            exchange: Optional explicit exchange.
        
        Returns:
            Dict mapping symbols to their LTP.
        
        Example:
            >>> ltps = dhan.get_ltp_batch(["NIFTY", "BANKNIFTY"])
            >>> print(ltps)
            {'NIFTY': 18050.0, 'BANKNIFTY': 42000.0}
        """
        quotes = self.get_quotes_batch(symbols, exchange)
        return {symbol: quote.ltp for symbol, quote in quotes.items()}
    
    def get_historical_batch(
        self,
        requests: List[Dict[str, Any]],
        continue_on_error: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Get historical data for multiple symbols (batch operation).
        
        Args:
            requests: List of request dicts with keys:
                - symbol: Symbol to get data for
                - from_date: Start date
                - to_date: End date
                - interval: Time interval (optional, default "1d")
                - exchange: Optional explicit exchange
            continue_on_error: Whether to continue if one request fails.
        
        Returns:
            Dict mapping symbols to their DataFrames.
        
        Example:
            >>> requests = [
            ...     {"symbol": "NIFTY", "from_date": "2024-01-01", "to_date": "2024-01-31"},
            ...     {"symbol": "BANKNIFTY", "from_date": "2024-01-01", "to_date": "2024-01-31"},
            ... ]
            >>> data = dhan.get_historical_batch(requests)
            >>> for sym, df in data.items():
            ...     print(f"{sym}: {len(df)} candles")
        """
        async def _get_batch():
            broker = await self._get_broker()
            result: Dict[str, pd.DataFrame] = {}
            
            for req in requests:
                symbol = req.get("symbol")
                if not symbol:
                    continue
                
                try:
                    from_date = self._parse_date(req.get("from_date"))
                    to_date = self._parse_date(req.get("to_date"))
                    interval = req.get("interval", "1d")
                    exchange = req.get("exchange")
                    
                    instrument = await self.resolve_symbol(symbol, exchange)
                    df = await broker._get_historical_async(
                        Instrument(
                            symbol=symbol,
                            exchange=instrument.exchange_segment.to_exchange(),
                            security_id=instrument.security_id
                        ),
                        from_date,
                        to_date,
                        interval
                    )
                    result[symbol] = df
                    
                except Exception as e:
                    logger.warning(f"Failed to get historical for {symbol}: {e}")
                    if not continue_on_error:
                        raise
            
            return result
        
        return self._run_async(_get_batch())
    
    # =========================================================================
    # Order Management - One-Liners
    # =========================================================================
    
    def place_order(
        self,
        symbol: str,
        side: Union[str, OrderSide],
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
        exchange: Optional[Exchange] = None,
        product_type: str = "M",
        validity: str = "DAY"
    ) -> Order:
        """
        Place an order (one-liner).
        
        Args:
            symbol: Symbol to trade.
            side: BUY or SELL (string or OrderSide enum).
            quantity: Order quantity.
            order_type: MARKET, LIMIT, SL, SL-M.
            price: Limit price (for LIMIT orders).
            trigger_price: Trigger price (for SL orders).
            exchange: Optional explicit exchange.
            product_type: I (Intraday), M (Margin), C (CNC).
            validity: DAY, IOC, GTC.
        
        Returns:
            Order with order_id and status.
        
        Example:
            >>> order = dhan.place_order("NIFTY", "BUY", 50)
            >>> print(order.order_id)
            '12345678'
        """
        # Parse side
        if isinstance(side, str):
            side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        
        async def _place():
            broker = await self._get_broker()
            instrument = await self.resolve_symbol(symbol, exchange)
            
            order = Order(
                instrument=Instrument(
                    symbol=symbol,
                    exchange=instrument.exchange_segment.to_exchange(),
                    security_id=instrument.security_id
                ),
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                trigger_price=trigger_price,
            )
            
            return await broker._place_order_async(order)
        
        return self._run_async(_place())
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order (one-liner).
        
        Args:
            order_id: Order ID to cancel.
        
        Returns:
            True if cancelled successfully.
        
        Example:
            >>> success = dhan.cancel_order("12345678")
            >>> print("Cancelled" if success else "Failed")
        """
        async def _cancel():
            broker = await self._get_broker()
            return await broker._cancel_order_async(order_id)
        
        return self._run_async(_cancel())
    
    def get_order_status(self, order_id: str) -> Order:
        """
        Get order status (one-liner).
        
        Args:
            order_id: Order ID.
        
        Returns:
            Order with current status.
        
        Example:
            >>> order = dhan.get_order_status("12345678")
            >>> print(order.status)
            OrderStatus.FILLED
        """
        async def _get_status():
            broker = await self._get_broker()
            return await broker._get_order_status_async(order_id)
        
        return self._run_async(_get_status())
    
    # =========================================================================
    # Portfolio - One-Liners
    # =========================================================================
    
    def get_positions(self) -> List[Position]:
        """
        Get all open positions (one-liner).
        
        Returns:
            List of open positions.
        
        Example:
            >>> positions = dhan.get_positions()
            >>> for pos in positions:
            ...     print(f"{pos.instrument.symbol}: {pos.quantity}")
        """
        async def _get_positions():
            broker = await self._get_broker()
            return await broker._get_positions_async()
        
        return self._run_async(_get_positions())
    
    def get_orderbook(self) -> List[Order]:
        """
        Get all orders (one-liner).
        
        Returns:
            List of orders.
        
        Example:
            >>> orders = dhan.get_orderbook()
            >>> for order in orders:
            ...     print(f"{order.instrument.symbol}: {order.status}")
        """
        async def _get_orderbook():
            broker = await self._get_broker()
            return await broker._get_orderbook_async()
        
        return self._run_async(_get_orderbook())
    
    # =========================================================================
    # Convenience Methods - Trade History, Trade Book, P&L
    # =========================================================================
    
    async def get_trade_history_async(
        self,
        from_date: Optional[Union[str, date, datetime]] = None,
        to_date: Optional[Union[str, date, datetime]] = None
    ) -> List[Trade]:
        """
        Get trade history for a period.
        
        Args:
            from_date: Start date (optional, defaults to today).
            to_date: End date (optional, defaults to today).
        
        Returns:
            List of trades.
        
        Example:
            >>> trades = await dhan.get_trade_history_async("2024-01-01", "2024-01-31")
            >>> for trade in trades:
            ...     print(f"{trade.symbol}: {trade.quantity}@{trade.price}")
        """
        broker = await self._get_broker()
        
        # Parse dates
        from_dt = self._parse_date(from_date) if from_date else datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        to_dt = self._parse_date(to_date) if to_date else datetime.now()
        
        # Get trade book from API
        try:
            response = await broker._http_client.get(
                endpoint=TRADES,
                params={
                    "from_date": from_dt.strftime("%Y-%m-%d"),
                    "to_date": to_dt.strftime("%Y-%m-%d"),
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"Failed to get trade history: {response.status_code}")
                return []
            
            trades = []
            for trade_data in response.data.get("data", []):
                trade = Trade(
                    trade_id=str(trade_data.get("tradeId", trade_data.get("trade_id", ""))),
                    order_id=str(trade_data.get("orderId", trade_data.get("order_id", ""))),
                    symbol=trade_data.get("tradingSymbol", trade_data.get("symbol", "")),
                    exchange=self._parse_exchange(trade_data.get("exchangeSegment", "")),
                    side=OrderSide.BUY if trade_data.get("transactionType", "").upper() == "BUY" else OrderSide.SELL,
                    quantity=int(trade_data.get("quantity", 0)),
                    price=float(trade_data.get("price", 0)),
                    timestamp=datetime.strptime(
                        trade_data.get("tradedAt", trade_data.get("timestamp", datetime.now().isoformat())),
                        "%Y-%m-%d %H:%M:%S"
                    ) if isinstance(trade_data.get("tradedAt", trade_data.get("timestamp")), str) else datetime.now(),
                    brokerage=float(trade_data.get("brokerage", 0)),
                    taxes=float(trade_data.get("taxes", 0)),
                )
                trades.append(trade)
            
            return trades
            
        except Exception as e:
            logger.error(f"Error getting trade history: {e}")
            return []
    
    def get_trade_history(
        self,
        from_date: Optional[Union[str, date, datetime]] = None,
        to_date: Optional[Union[str, date, datetime]] = None
    ) -> List[Trade]:
        """
        Get trade history for a period (synchronous).
        
        Args:
            from_date: Start date (optional).
            to_date: End date (optional).
        
        Returns:
            List of trades.
        
        Example:
            >>> trades = dhan.get_trade_history("2024-01-01", "2024-01-31")
        """
        return self._run_async(self.get_trade_history_async(from_date, to_date))
    
    async def get_trade_book_async(self) -> List[Trade]:
        """
        Get today's trades.
        
        Returns:
            List of today's trades.
        
        Example:
            >>> trades = await dhan.get_trade_book_async()
            >>> for trade in trades:
            ...     print(f"{trade.symbol}: {trade.side.value} {trade.quantity}@{trade.price}")
        """
        return await self.get_trade_history_async()
    
    def get_trade_book(self) -> List[Trade]:
        """
        Get today's trades (synchronous).
        
        Returns:
            List of today's trades.
        
        Example:
            >>> trades = dhan.get_trade_book()
        """
        return self._run_async(self.get_trade_book_async())
    
    async def get_pnl_async(
        self,
        from_date: Optional[Union[str, date, datetime]] = None,
        to_date: Optional[Union[str, date, datetime]] = None
    ) -> PnLReport:
        """
        Get P&L report for a period.
        
        Args:
            from_date: Start date (optional).
            to_date: End date (optional).
        
        Returns:
            PnLReport with realized and unrealized P&L.
        
        Example:
            >>> pnl = await dhan.get_pnl_async("2024-01-01", "2024-01-31")
            >>> print(f"Realized: {pnl.realized_pnl}, Unrealized: {pnl.unrealized_pnl}")
        """
        broker = await self._get_broker()
        
        # Get positions for unrealized P&L
        positions = await broker._get_positions_async()
        unrealized_pnl = sum(pos.pnl for pos in positions if hasattr(pos, 'pnl'))
        
        # Get trades for realized P&L
        trades = await self.get_trade_history_async(from_date, to_date)
        
        # Calculate realized P&L from trades
        realized_pnl = 0.0
        for trade in trades:
            # Deduct brokerage and taxes
            realized_pnl -= (trade.brokerage + trade.taxes)
        
        # Try to get P&L from API
        try:
            response = await broker._http_client.get(endpoint=PNL)
            if response.status_code == 200:
                data = response.data.get("data", {})
                realized_pnl = float(data.get("realizedPnl", realized_pnl))
                unrealized_pnl = float(data.get("unrealizedPnl", unrealized_pnl))
        except Exception as e:
            logger.warning(f"Could not fetch P&L from API: {e}")
        
        return PnLReport(
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=realized_pnl + unrealized_pnl,
            trades=trades,
            positions=positions,
        )
    
    def get_pnl(
        self,
        from_date: Optional[Union[str, date, datetime]] = None,
        to_date: Optional[Union[str, date, datetime]] = None
    ) -> PnLReport:
        """
        Get P&L report for a period (synchronous).
        
        Args:
            from_date: Start date (optional).
            to_date: End date (optional).
        
        Returns:
            PnLReport with realized and unrealized P&L.
        
        Example:
            >>> pnl = dhan.get_pnl("2024-01-01", "2024-01-31")
            >>> print(f"Total P&L: {pnl.total_pnl}")
        """
        return self._run_async(self.get_pnl_async(from_date, to_date))
    
    def _parse_exchange(self, exchange_str: str) -> Exchange:
        """Parse exchange string to Exchange enum."""
        exchange_map = {
            "NSE_EQ": Exchange.NSE,
            "NSE_FNO": Exchange.NFO,
            "BSE_EQ": Exchange.BSE,
            "BSE_FNO": Exchange.BFO,
            "MCX_COMM": Exchange.MCX,
            "MCX": Exchange.MCX,
        }
        return exchange_map.get(exchange_str.upper(), Exchange.NSE)
    
    # =========================================================================
    # Context Manager Support
    # =========================================================================
    
    async def __aenter__(self) -> "DhanFacade":
        """Enter async context manager."""
        await self._get_broker()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        if self._broker:
            await self._broker.close()
    
    # =========================================================================
    # String Representation
    # =========================================================================
    
    def __repr__(self) -> str:
        """Return string representation."""
        return f"DhanFacade(client_id={self._client_id!r})"
