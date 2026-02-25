"""
Broker Gateway - Unified API for broker operations.

Provides:
- Factory pattern for broker creation
- Synchronous API for simple operations
- Reactive API (Rx) for streaming data
- Circuit breaker for fault tolerance
"""

import logging
from typing import Optional, List, Dict, Type, Any
from datetime import datetime
import asyncio
from enum import Enum

from brokers.broker.ports import IBrokerPort, CircuitBreaker, CircuitBreakerError
from brokers.broker.logging import get_logger, setup_logging, correlation_context
from brokers.broker.resilience import CircuitState, CircuitBreakerConfig  # noqa: F401 – re-exported
from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OptionChain,
    MarketDepth,
)
from brokers.broker.types import Exchange

logger = get_logger("gateway")


# =============================================================================
# Broker Type Enum
# =============================================================================


class BrokerType(str, Enum):
    """Supported broker types."""

    PAPER = "paper"
    DHAN = "dhan"
    # Future brokers can be added here
    # ZERODHA = "zerodha"
    # UPSTOX = "upstox"


# =============================================================================
# Broker Factory
# =============================================================================


class BrokerFactory:
    """
    Factory for creating broker instances.

    Provides a centralized way to create and configure brokers.
    Supports dependency injection for testing.

    Usage:
        # Create paper broker (for testing)
        broker = BrokerFactory.create(BrokerType.PAPER)

        # Create Dhan broker (reads credentials from env)
        broker = BrokerFactory.create(BrokerType.DHAN)

        # Create Dhan broker with explicit credentials
        broker = BrokerFactory.create(
            BrokerType.DHAN,
            client_id='xxx',
            access_token='yyy'
        )
    """

    _registry: Dict[BrokerType, Type[IBrokerPort]] = {}

    @classmethod
    def register(cls, broker_type: BrokerType, broker_class: Type[IBrokerPort]):
        """
        Register a broker class for a given type.

        Allows extending the factory with custom broker implementations.

        Args:
            broker_type: The broker type identifier
            broker_class: The broker class (must implement IBrokerPort)
        """
        cls._registry[broker_type] = broker_class

    @classmethod
    def create(cls, broker_type: BrokerType, **kwargs) -> IBrokerPort:
        """
        Create a broker instance.

        Args:
            broker_type: Type of broker to create
            **kwargs: Additional arguments passed to broker constructor

        Returns:
            Configured broker instance

        Raises:
            ValueError: If broker type is not registered
        """
        # Check custom registry first (allows overriding defaults)
        if broker_type in cls._registry:
            broker_class = cls._registry[broker_type]
            return broker_class(**kwargs)

        # Lazy import to avoid circular dependencies
        if broker_type == BrokerType.PAPER:
            from brokers.broker.paper import PaperBroker

            return PaperBroker(**kwargs)
        elif broker_type == BrokerType.DHAN:
            from brokers.broker.dhan import DhanBroker
            from brokers.broker.dhan.application.config import DhanConfig

            client_id = kwargs.pop("client_id", None)
            access_token = kwargs.pop("access_token", None)

            if client_id and access_token:
                return DhanBroker.create(
                    client_id=client_id, access_token=access_token, **kwargs
                )
            else:
                # Auto-load credentials from .env / environment
                config = DhanConfig.from_env()
                return DhanBroker.create(
                    client_id=config.client_id,
                    access_token=config.access_token,
                    **kwargs,
                )

        raise ValueError(f"Unknown broker type: {broker_type}")

    @classmethod
    def available_brokers(cls) -> List[str]:
        """Get list of available broker types."""
        return [bt.value for bt in BrokerType]


# =============================================================================
# Circuit Breaker (using unified implementation from broker/ports.py)
# =============================================================================

# CircuitBreaker and CircuitBreakerError are imported at the top of this module
# from broker.ports and thus available as gateway.CircuitBreaker for backward compat.


# =============================================================================
# Broker Gateway - Unified API
# =============================================================================


class BrokerGateway:
    """
    Unified gateway for broker operations.

    Provides:
    - Factory pattern for broker creation
    - Circuit breaker for fault tolerance
    - Clean API for both sync and async operations

    Usage:
        # Create gateway with paper broker
        gateway = BrokerGateway.paper()

        # Create gateway with Dhan broker
        gateway = BrokerGateway.dhan()

        # Use sync API
        quote = gateway.get_quote("RELIANCE", Exchange.NSE)

        # Use reactive API
        async for tick in gateway.stream_ticker(["RELIANCE"]):
            print(tick)
    """

    def __init__(
        self,
        broker: IBrokerPort,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        """
        Initialize gateway with a broker.

        Args:
            broker: The broker implementation to use
            circuit_breaker: Optional circuit breaker for fault tolerance
        """
        self._broker = broker
        self._circuit_breaker = circuit_breaker or CircuitBreaker()

    # -------------------------------------------------------------------------
    # Logging Configuration
    # -------------------------------------------------------------------------

    @staticmethod
    def configure_logging(
        level: int = logging.INFO,
        format_type: str = "text",
    ) -> None:
        """
        Configure structured logging for the brokers module.

        Call once at application startup before creating gateways.

        Args:
            level: Logging level (logging.DEBUG, logging.INFO, etc.)
            format_type: "json" for machine-readable or "text" for human-readable
        """
        setup_logging(level=level, format_type=format_type)
        logger.info(
            "Logging configured",
            extra={"level": logging.getLevelName(level), "format": format_type},
        )

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def paper(cls, **kwargs) -> "BrokerGateway":
        """Create gateway with paper broker."""
        broker = BrokerFactory.create(BrokerType.PAPER, **kwargs)
        return cls(broker)

    @classmethod
    def dhan(
        cls,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        **kwargs,
    ) -> "BrokerGateway":
        """Create gateway with Dhan broker."""
        broker = BrokerFactory.create(
            BrokerType.DHAN, client_id=client_id, access_token=access_token, **kwargs
        )
        return cls(broker)

    @classmethod
    def create(cls, broker_type: BrokerType, **kwargs) -> "BrokerGateway":
        """Create gateway with specified broker type."""
        broker = BrokerFactory.create(broker_type, **kwargs)
        return cls(broker)

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def broker(self) -> IBrokerPort:
        """Access underlying broker."""
        return self._broker

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access circuit breaker."""
        return self._circuit_breaker

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """Close the gateway and release broker resources."""
        logger.debug("Closing gateway")
        # DhanBroker.close() is async; use close_sync() if available
        close_fn = getattr(self._broker, "close_sync", None) or self._broker.close
        close_fn()

    def __enter__(self) -> "BrokerGateway":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # No __del__ — callers must use context manager or call close() explicitly.
    # DhanBroker has its own __del__ as a last-resort guard.

    # -------------------------------------------------------------------------
    # Synchronous API
    # -------------------------------------------------------------------------

    def get_quote(
        self, symbol: str, exchange: Exchange = Exchange.NSE, security_id: str = ""
    ) -> Quote:
        """
        Get quote for a symbol.

        Args:
            symbol: Trading symbol
            exchange: Exchange (default: NSE)
            security_id: Optional security ID

        Returns:
            Quote entity
        """
        with correlation_context() as cid:
            logger.debug("get_quote", extra={"symbol": symbol, "exchange": exchange.value, "cid": cid})
            instrument = Instrument(
                symbol=symbol, exchange=exchange, security_id=security_id
            )
            with self._circuit_breaker:
                return self._broker.get_quote(instrument)

    def get_quotes(
        self, symbols: List[str], exchange: Exchange = Exchange.NSE
    ) -> Dict[str, Quote]:
        """
        Get quotes for multiple symbols.

        Args:
            symbols: List of trading symbols
            exchange: Exchange (default: NSE)

        Returns:
            Dict mapping symbol to Quote
        """
        with correlation_context() as cid:
            logger.debug("get_quotes", extra={"symbols": symbols, "exchange": exchange.value, "cid": cid})
            instruments = [
                Instrument(symbol=s, exchange=exchange, security_id="") for s in symbols
            ]
            with self._circuit_breaker:
                quotes = self._broker.get_quotes_batch(instruments)
                return {q.instrument.symbol: q for q in quotes.values()}

    def get_option_chain(
        self, underlying: str, exchange: Exchange = Exchange.NFO, expiry_index: int = 0
    ) -> OptionChain:
        """
        Get option chain for an underlying.

        Args:
            underlying: Underlying symbol (e.g., "NIFTY")
            exchange: Exchange (default: NFO)
            expiry_index: Expiry index (0 = nearest)

        Returns:
            OptionChain entity
        """
        with correlation_context() as cid:
            logger.debug("get_option_chain", extra={"underlying": underlying, "exchange": exchange.value, "cid": cid})
            with self._circuit_breaker:
                return self._broker.get_option_chain(underlying, exchange, expiry_index)

    def get_expiries(
        self, underlying: str, exchange: Exchange = Exchange.NFO
    ) -> List[datetime]:
        """
        Get expiry dates for an underlying.

        Args:
            underlying: Underlying symbol
            exchange: Exchange

        Returns:
            List of expiry dates
        """
        with correlation_context() as cid:
            logger.debug("get_expiries", extra={"underlying": underlying, "cid": cid})
            with self._circuit_breaker:
                return self._broker.get_expiry_list(underlying, exchange)

    def get_historical(
        self,
        symbol: str,
        exchange: Exchange,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        security_id: str = "",
        include_oi: bool = False,
    ):
        """
        Get historical OHLCV data for a symbol.

        Returns:
            DataFrame with columns: open, high, low, close, volume (and optionally oi)
        """
        with correlation_context() as cid:
            logger.debug("get_historical", extra={"symbol": symbol, "exchange": exchange.value, "cid": cid})
            instrument = Instrument(symbol=symbol, exchange=exchange, security_id=security_id)
            with self._circuit_breaker:
                return self._broker.get_historical(instrument, from_date, to_date, interval, include_oi)

    def place_order(
        self,
        symbol: str,
        exchange: Exchange,
        side: str,
        quantity: int,
        price: float = 0,
        security_id: str = "",
        trigger_price: Optional[float] = None,
        product_type: str = "INTRADAY",
    ) -> Order:
        """
        Place an order.

        Args:
            symbol:        Trading symbol
            exchange:      Exchange
            side:          "BUY" or "SELL"
            quantity:      Order quantity
            price:         Limit price (0 for MARKET orders)
            security_id:   Optional security ID
            trigger_price: Stop-loss activation price (for SL / SLM orders)
            product_type:  INTRADAY | CNC | MARGIN | CO | BO (default: INTRADAY)

        Returns:
            Order entity with order_id populated by broker
        """
        from brokers.broker.types import OrderSide

        with correlation_context() as cid:
            logger.info("place_order", extra={"symbol": symbol, "side": side, "qty": quantity, "cid": cid})
            instrument = Instrument(
                symbol=symbol, exchange=exchange, security_id=security_id
            )
            order = Order(
                instrument=instrument,
                side=OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL,
                quantity=quantity,
                price=price if price is not None else None,
                trigger_price=trigger_price,
                product_type=product_type,
            )
            with self._circuit_breaker:
                return self._broker.place_order(order)

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order via the broker.

        Wraps the call in the circuit breaker so failures count toward the
        fault-tolerance threshold.

        Args:
            order_id: Broker-assigned order ID to cancel

        Returns:
            True if cancellation was accepted
        """
        with correlation_context() as cid:
            logger.info("cancel_order", extra={"order_id": order_id, "cid": cid})
            with self._circuit_breaker:
                return self._broker.cancel_order(order_id)

    def get_order_status(self, order_id: str) -> Order:
        """
        Query the current status of an order.

        Args:
            order_id: Broker-assigned order ID

        Returns:
            Order entity with current status
        """
        with correlation_context() as cid:
            logger.debug("get_order_status", extra={"order_id": order_id, "cid": cid})
            with self._circuit_breaker:
                return self._broker.get_order_status(order_id)

    def get_positions(self) -> List[Position]:
        """Get current positions."""
        with correlation_context() as cid:
            logger.debug("get_positions", extra={"cid": cid})
            with self._circuit_breaker:
                return self._broker.get_positions()

    # -------------------------------------------------------------------------
    # Reactive API (Async)
    # -------------------------------------------------------------------------

    async def stream_ticker(
        self, symbols: List[str], exchange: Exchange = Exchange.NSE
    ):
        """
        Stream ticker data for symbols.

        Args:
            symbols: List of trading symbols
            exchange: Exchange

        Yields:
            Tick entities
        """
        instruments = [
            Instrument(symbol=s, exchange=exchange, security_id="") for s in symbols
        ]

        async for tick in self._broker.stream_ticker(instruments):
            yield tick

    async def stream_quotes(
        self, symbols: List[str], exchange: Exchange = Exchange.NSE
    ):
        """
        Stream quote data for symbols.

        Args:
            symbols: List of trading symbols
            exchange: Exchange

        Yields:
            Quote entities
        """
        instruments = [
            Instrument(symbol=s, exchange=exchange, security_id="") for s in symbols
        ]

        async for quote in self._broker.stream_quotes(instruments):
            yield quote

    async def stream_full(
        self, symbols: List[str], exchange: Exchange = Exchange.MCX
    ):
        """
        Stream full market data (LTP + volume + L1 bid/ask) for symbols.
        Required for MCX — TICKER and QUOTE feeds are not supported there.

        Yields:
            Raw dicts with keys: ltp, open, high, low, close, volume, oi, atp,
            depth_bids, depth_asks, security_id, exchange_segment, symbol, timestamp
        """
        instruments = [
            Instrument(symbol=s, exchange=exchange, security_id="") for s in symbols
        ]
        async for pkt in self._broker.stream_full(instruments):
            yield pkt

    async def stream_depth(
        self,
        symbols: List[str],
        exchange: Exchange = Exchange.NSE,
        depth_level: int = 20,
    ):
        """
        Stream 20-level market depth data for symbols.

        Args:
            symbols: List of trading symbols
            exchange: Exchange
            depth_level: Number of depth levels (default 20)

        Yields:
            MarketDepth entities
        """
        instruments = [
            Instrument(symbol=s, exchange=exchange, security_id="") for s in symbols
        ]

        async for depth in self._broker.stream_depth(instruments, depth_level):
            yield depth

    async def stream_depth_20(
        self,
        symbols: List[str],
        exchange: Exchange = Exchange.NSE,
    ):
        """
        Stream 20-level market depth via the dedicated depth feed.

        Uses the dedicated depth WebSocket endpoint (up to 50 NSE instruments).

        Args:
            symbols: List of trading symbols
            exchange: Exchange

        Yields:
            MarketDepth entities with 20 bid/ask levels each
        """
        instruments = [
            Instrument(symbol=s, exchange=exchange, security_id="") for s in symbols
        ]

        async for depth in self._broker.stream_depth_20(instruments):
            yield depth

    async def stream_depth_200(
        self,
        symbol: str,
        exchange: Exchange = Exchange.NSE,
    ):
        """
        Stream 200-level market depth via the full-depth feed.

        Uses the dedicated full-depth WebSocket endpoint (1 instrument only).

        Args:
            symbol: Single trading symbol
            exchange: Exchange

        Yields:
            MarketDepth entities with up to 200 bid/ask levels each
        """
        instruments = [Instrument(symbol=symbol, exchange=exchange, security_id="")]

        async for depth in self._broker.stream_depth_200(instruments):
            yield depth


# =============================================================================
# Convenience Functions
# =============================================================================


def create_paper_gateway(**kwargs) -> BrokerGateway:
    """Create a paper trading gateway."""
    return BrokerGateway.paper(**kwargs)


def create_dhan_gateway(
    client_id: Optional[str] = None, access_token: Optional[str] = None, **kwargs
) -> BrokerGateway:
    """Create a Dhan broker gateway."""
    return BrokerGateway.dhan(client_id=client_id, access_token=access_token, **kwargs)
