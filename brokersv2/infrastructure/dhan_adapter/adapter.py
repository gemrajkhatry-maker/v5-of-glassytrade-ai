"""
DhanHQ v2 broker adapter implementation - FULLY ASYNC.

CRITICAL FIX: Removed all asyncio.run() anti-patterns.
All methods are now properly async/await.
"""

from __future__ import annotations

from typing import List, Optional, AsyncIterator, TYPE_CHECKING
import logging

from brokersv2.core.ports import IBrokerAdapter
from brokersv2.domain.order.models import Order, OrderStatus
from brokersv2.domain.market.models import Tick, Quote, Candle
from brokersv2.infrastructure.dhan_adapter.client import DhanHttpClient, DhanConfig
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter
from brokersv2.core.resilience import CircuitBreaker

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


class DhanBrokerAdapter(IBrokerAdapter):
    """
    DhanHQ v2 broker adapter - FULLY ASYNC IMPLEMENTATION.
    
    Implements IBrokerAdapter by translating between canonical instruments
    and broker-specific formats.
    
    CRITICAL FEATURES:
    - Fully async/await (NO asyncio.run() anti-patterns)
    - WebSocket streaming support
    - Circuit breaker integration
    - Rate limiting
    - Instrument mapping
    - DRY_RUN support
    """
    
    def __init__(
        self,
        config: DhanConfig,
        mapper: InstrumentMapper,
        rate_limiter: Optional[RateLimiter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        dry_run: bool = False,
    ):
        """
        Initialize Dhan broker adapter.
        
        Args:
            config: DhanHQ configuration
            mapper: Instrument mapper for canonical ↔ broker translation
            rate_limiter: Rate limiter for API calls
            circuit_breaker: Circuit breaker for fault tolerance
            dry_run: If True, don't actually send orders to broker
        """
        self._config = config
        self._mapper = mapper
        self._client = DhanHttpClient(config, rate_limiter)
        self._rate_limiter = rate_limiter or RateLimiter()
        self._circuit_breaker = circuit_breaker
        self._dry_run = dry_run
        
        logger.info(
            f"DhanBrokerAdapter initialized (dry_run={dry_run})"
        )
    
    @classmethod
    def create(
        cls,
        client_id: str,
        access_token: str,
        mapper: InstrumentMapper,
        rate_limiter: Optional[RateLimiter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        dry_run: bool = False,
        **kwargs,
    ) -> "DhanBrokerAdapter":
        """Factory method for creating broker adapter."""
        config = DhanConfig(
            client_id=client_id,
            access_token=access_token,
            **kwargs,
        )
        return cls(
            config=config,
            mapper=mapper,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
            dry_run=dry_run,
        )
    
    async def close(self) -> None:
        """Close the broker connection."""
        await self._client.close()
        logger.info("DhanBrokerAdapter closed")
    
    # IBrokerAdapter implementation - ALL ASYNC
    
    async def place_order(self, order: Order) -> str:
        """
        Place order and return broker order ID.
        
        FULLY ASYNC - NO asyncio.run()
        
        Args:
            order: Order to place
            
        Returns:
            Broker order ID
            
        Raises:
            BrokerConnectionError: If API call fails
            BrokerAuthenticationError: If auth fails
        """
        if self._dry_run:
            logger.info(f"[DRY_RUN] Would place order: {order.order_id}")
            return f"DRY_RUN_{order.order_id}"
        
        # Circuit breaker check
        if self._circuit_breaker:
            with self._circuit_breaker:
                broker_order_id = await self._client.place_order(order, self._mapper)
        else:
            broker_order_id = await self._client.place_order(order, self._mapper)
        
        logger.info(f"Order placed: {order.order_id} -> {broker_order_id}")
        return broker_order_id
    
    async def cancel_order(self, broker_order_id: str) -> bool:
        """
        Cancel order by broker order ID.
        
        FULLY ASYNC - NO asyncio.run()
        
        Args:
            broker_order_id: Broker's order ID
            
        Returns:
            True if cancelled successfully
        """
        if self._dry_run:
            logger.info(f"[DRY_RUN] Would cancel order: {broker_order_id}")
            return True
        
        if self._circuit_breaker:
            with self._circuit_breaker:
                result = await self._client.cancel_order(broker_order_id)
        else:
            result = await self._client.cancel_order(broker_order_id)
        
        logger.info(f"Order cancelled: {broker_order_id}")
        return result
    
    async def get_order_status(self, broker_order_id: str) -> Order:
        """
        Get order status.
        
        FULLY ASYNC - NO asyncio.run()
        
        Args:
            broker_order_id: Broker's order ID
            
        Returns:
            Order with current status
        """
        if self._circuit_breaker:
            with self._circuit_breaker:
                order = await self._client.get_order_status(broker_order_id)
        else:
            order = await self._client.get_order_status(broker_order_id)
        
        return order
    
    async def get_quote(self, instrument: "CanonicalInstrument") -> Quote:
        """
        Get current quote.
        
        FULLY ASYNC - NO asyncio.run()
        
        Args:
            instrument: Canonical instrument
            
        Returns:
            Current quote
        """
        if self._circuit_breaker:
            with self._circuit_breaker:
                quote = await self._client.get_quote(instrument, self._mapper)
        else:
            quote = await self._client.get_quote(instrument, self._mapper)
        
        return quote
    
    async def stream_ticks(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> AsyncIterator[Tick]:
        """
        Stream real-time ticks via WebSocket.
        
        FULLY ASYNC - Uses WebSocket connection for live data.
        
        Args:
            instruments: List of instruments to stream
            
        Yields:
            Tick data as it arrives
        """
        # Import WebSocket manager
        from brokersv2.websocket.manager import WebSocketManager
        
        # Create WebSocket manager
        ws_manager = WebSocketManager(
            config=self._config,
            mapper=self._mapper,
        )
        
        try:
            # Start WebSocket connection
            await ws_manager.start()
            
            # Subscribe to instruments
            await ws_manager.subscribe(instruments)
            
            # Stream ticks
            async for tick in ws_manager.stream_ticks():
                yield tick
                
        except Exception as e:
            logger.error(f"WebSocket streaming error: {e}")
            raise
        finally:
            await ws_manager.stop()
    
    async def get_historical(
        self,
        instrument: "CanonicalInstrument",
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> List[Candle]:
        """
        Get historical data.
        
        FULLY ASYNC - NO asyncio.run()
        
        Args:
            instrument: Canonical instrument
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            interval: Candle interval (1m, 5m, 15m, 1h, 1d)
            
        Returns:
            List of candles
        """
        if self._circuit_breaker:
            with self._circuit_breaker:
                candles = await self._client.get_historical(
                    instrument, from_date, to_date, interval, self._mapper
                )
        else:
            candles = await self._client.get_historical(
                instrument, from_date, to_date, interval, self._mapper
            )
        
        return candles
    
    async def get_option_chain(
        self,
        symbol: str,
        exchange: "Exchange",
        expiry_index: int = 0,
    ) -> "OptionChainData":
        """
        Get option chain and normalize to domain model.
        
        FULLY ASYNC - NO asyncio.run()
        
        Args:
            symbol: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            exchange: Exchange enum (NSE, BSE, etc.)
            expiry_index: Expiry selection (0=current, 1=near, 2=far)
            
        Returns:
            OptionChainData domain object with normalized option contracts
        """
        from brokersv2.analytics.options.events import (
            OptionContract,
            OptionType,
            StrikeLevel,
            OptionChainEvent,
        )
        from brokersv2.domain.options.models import OptionChainData
        from datetime import datetime, timezone
        
        # Fetch raw option chain from DhanHQ
        if self._circuit_breaker:
            with self._circuit_breaker:
                raw_data = await self._client.get_option_chain(
                    symbol=symbol,
                    exchange=exchange.value if hasattr(exchange, 'value') else str(exchange),
                    expiry_index=expiry_index,
                    mapper=self._mapper,
                )
        else:
            raw_data = await self._client.get_option_chain(
                symbol=symbol,
                exchange=exchange.value if hasattr(exchange, 'value') else str(exchange),
                expiry_index=expiry_index,
                mapper=self._mapper,
            )
        
        # Parse and normalize to domain models
        option_chain_data = OptionChainData(
            underlying=symbol,
            exchange=exchange,
            expiry_index=expiry_index,
            raw_data=raw_data,
        )
        
        # Extract expiry date from raw data
        # DhanHQ returns expiry as string in response
        expiry_str = raw_data.get("expiry") or raw_data.get("expiryDate")
        if expiry_str:
            try:
                option_chain_data.expiry_date = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Try YYYY-MM-DD format
                try:
                    from datetime import date
                    date_obj = date.fromisoformat(expiry_str)
                    option_chain_data.expiry_date = datetime.combine(date_obj, datetime.min.time(), tzinfo=timezone.utc)
                except (ValueError, AttributeError):
                    logger.warning(f"Could not parse expiry date: {expiry_str}")
        
        # Extract option chain data
        # DhanHQ response structure: {"data": {"oc": {strike: {ce: {...}, pe: {...}}}, "last_price": ...}}
        data_section = raw_data.get("data", {})
        if isinstance(data_section, list):
            data_section = data_section[0] if data_section else {}
        
        oc_data = data_section.get("oc", {})
        
        # Set underlying price (spot price)
        underlying_price = float(data_section.get("last_price", 0) or 0)
        option_chain_data.underlying_price = underlying_price
        
        # Parse each strike
        for strike_str, opt_data in oc_data.items():
            try:
                strike_price = float(strike_str)
            except (ValueError, TypeError):
                continue
            
            ce_data = opt_data.get("ce", {}) if isinstance(opt_data, dict) else {}
            pe_data = opt_data.get("pe", {}) if isinstance(opt_data, dict) else {}
            
            # Parse Call option
            if ce_data and ce_data.get("security_id"):
                call_contract = OptionContract(
                    symbol=ce_data.get("symbol", f"{symbol}{int(strike_price)}CE"),
                    underlying=symbol,
                    strike=strike_price,
                    expiry=option_chain_data.expiry_date or datetime.now(timezone.utc),
                    option_type=OptionType.CALL,
                    ltp=float(ce_data.get("last_price", 0) or 0),
                    bid=float(ce_data.get("top_bid_price", 0) or 0),
                    ask=float(ce_data.get("top_ask_price", 0) or 0),
                    volume=int(ce_data.get("volume", 0) or 0),
                    open_interest=int(ce_data.get("oi", 0) or 0),
                    implied_volatility=float(ce_data.get("implied_volatility", 0) or 0),
                    delta=float((ce_data.get("greeks") or {}).get("delta", 0) or 0),
                    gamma=float((ce_data.get("greeks") or {}).get("gamma", 0) or 0),
                    theta=float((ce_data.get("greeks") or {}).get("theta", 0) or 0),
                    vega=float((ce_data.get("greeks") or {}).get("vega", 0) or 0),
                )
                option_chain_data.add_option(call_contract)
            
            # Parse Put option
            if pe_data and pe_data.get("security_id"):
                put_contract = OptionContract(
                    symbol=pe_data.get("symbol", f"{symbol}{int(strike_price)}PE"),
                    underlying=symbol,
                    strike=strike_price,
                    expiry=option_chain_data.expiry_date or datetime.now(timezone.utc),
                    option_type=OptionType.PUT,
                    ltp=float(pe_data.get("last_price", 0) or 0),
                    bid=float(pe_data.get("top_bid_price", 0) or 0),
                    ask=float(pe_data.get("top_ask_price", 0) or 0),
                    volume=int(pe_data.get("volume", 0) or 0),
                    open_interest=int(pe_data.get("oi", 0) or 0),
                    implied_volatility=float(pe_data.get("implied_volatility", 0) or 0),
                    delta=float((pe_data.get("greeks") or {}).get("delta", 0) or 0),
                    gamma=float((pe_data.get("greeks") or {}).get("gamma", 0) or 0),
                    theta=float((pe_data.get("greeks") or {}).get("theta", 0) or 0),
                    vega=float((pe_data.get("greeks") or {}).get("vega", 0) or 0),
                )
                option_chain_data.add_option(put_contract)
        
        logger.info(
            f"Option chain loaded: {symbol} "
            f"expiry={option_chain_data.expiry_date} "
            f"strikes={len(option_chain_data.strikes)} "
            f"underlying_price={underlying_price}"
        )
        
        return option_chain_data
    
    async def get_positions(self) -> List[dict]:
        """
        Get current positions.
        
        FULLY ASYNC
        
        Returns:
            List of position dicts
        """
        if self._circuit_breaker:
            with self._circuit_breaker:
                positions = await self._client.get_positions()
        else:
            positions = await self._client.get_positions()
        
        return positions
    
    async def get_portfolio(self) -> dict:
        """
        Get portfolio summary.
        
        FULLY ASYNC
        
        Returns:
            Portfolio summary dict
        """
        if self._circuit_breaker:
            with self._circuit_breaker:
                portfolio = await self._client.get_portfolio()
        else:
            portfolio = await self._client.get_portfolio()
        
        return portfolio
    
    @property
    def client(self) -> DhanHttpClient:
        """Access underlying HTTP client."""
        return self._client
    
    @property
    def rate_limiter(self) -> RateLimiter:
        """Access rate limiter."""
        return self._rate_limiter
    
    @property
    def circuit_breaker(self) -> Optional[CircuitBreaker]:
        """Access circuit breaker."""
        return self._circuit_breaker
    
    @property
    def dry_run(self) -> bool:
        """Check if in dry run mode."""
        return self._dry_run
    
    def set_dry_run(self, enabled: bool):
        """
        Enable/disable dry run mode.
        
        Args:
            enabled: If True, don't send orders to broker
        """
        self._dry_run = enabled
        logger.info(f"Dry run mode: {enabled}")
