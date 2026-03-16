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

from brokers.broker.ports import IBrokerPort
from brokers.broker.logging import get_logger, setup_logging, correlation_context
from shared.entities.models import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OrderStatus,
    Exchange
)
from shared.resilience import CircuitBreaker, CircuitBreakerError, CircuitState

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


# CircuitBreaker and CircuitBreakerError are imported from shared.resilience

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
        from brokers.broker.ports import CircuitBreakerWrapper
        
        self._raw_broker = broker
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._broker = CircuitBreakerWrapper(broker, self._circuit_breaker)

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
        """Access underlying protected broker."""
        return self._broker

    @property
    def raw_broker(self) -> IBrokerPort:
        """Access underlying raw broker (without circuit breaker)."""
        return self._raw_broker

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
        close_fn = getattr(self._raw_broker, "close_sync", None) or self._broker.close
        close_fn()

    def __enter__(self) -> "BrokerGateway":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # -------------------------------------------------------------------------
    # Market Data
    # -------------------------------------------------------------------------

    def get_quote(self, symbol: str, exchange: Exchange) -> Quote:
        instrument = Instrument(symbol=symbol, exchange=exchange)
        return self._broker.get_quote(instrument)

    def get_quotes(self, symbols: List[str], exchange: Exchange) -> Dict[str, Quote]:
        instruments = [Instrument(symbol=s, exchange=exchange) for s in symbols]
        quotes = self._broker.get_quotes_batch(instruments)
        return {q.instrument.symbol: q for q in quotes.values()}

    def get_quotes_batch(self, instruments: List[Instrument]) -> Dict[Instrument, Quote]:
        return self._broker.get_quotes_batch(instruments)

    def get_historical(
        self,
        symbol: str,
        exchange: Exchange,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        include_oi: bool = False,
    ):
        instrument = Instrument(symbol=symbol, exchange=exchange)
        return self._broker.get_historical(
            instrument, from_date, to_date, interval, include_oi
        )

    # -------------------------------------------------------------------------
    # Order Execution (Intercepted when DRY_RUN=True)
    # -------------------------------------------------------------------------

    def place_order(self, order: Optional[Order] = None, **kwargs) -> Order:
        if order is None:
            order = Order(**kwargs)
        from app.config import settings
        if settings.DRY_RUN:
            logger.warning("[DRY_RUN] Intercepted place_order: %s", order)
            order.status = OrderStatus.COMPLETED
            order.order_id = f"mock_order_{datetime.now().timestamp()}"
            return order
        return self._broker.place_order(order)

    def cancel_order(self, order_id: str) -> bool:
        from app.config import settings
        if settings.DRY_RUN:
            if order_id.startswith("mock_order_"):
                logger.warning("[DRY_RUN] Intercepted cancel_order for mock ID %s", order_id)
                return True
        return self._broker.cancel_order(order_id)

    def get_order_status(self, order_id: str) -> Order:
        from app.config import settings
        if settings.DRY_RUN:
            if order_id.startswith("mock_order_"):
                # Return a dummy completed order
                return Order(
                    symbol="MOCK", exchange=Exchange.NSE, 
                    quantity=1, side="BUY", order_type="MARKET", 
                    status=OrderStatus.COMPLETED, order_id=order_id
                )
        return self._broker.get_order_status(order_id)

    def get_expiry_list(self, symbol: str, exchange: Exchange) -> List[datetime]:
        """Get expiry list for underlying symbol."""
        return self._broker.get_expiry_list(symbol, exchange)

    def get_expiries(self, symbol: str, exchange: Exchange) -> List[datetime]:
        """Alias for get_expiry_list."""
        return self.get_expiry_list(symbol, exchange)

    def get_option_chain(
        self, symbol: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain:
        """Get option chain for underlying symbol."""
        return self._broker.get_option_chain(symbol, exchange, expiry_index)

    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------

    async def stream_ticker(self, symbols: Union[str, List[str]], exchange: Exchange):
        if isinstance(symbols, str):
            symbols = [symbols]
        instruments = [Instrument(symbol=s, exchange=exchange) for s in symbols]
        async for tick in self._broker.stream_ticker(instruments):
            yield tick

    async def stream_quotes(self, symbols: Union[str, List[str]], exchange: Exchange):
        if isinstance(symbols, str):
            symbols = [symbols]
        instruments = [Instrument(symbol=s, exchange=exchange) for s in symbols]
        async for quote in self._broker.stream_quotes(instruments):
            yield quote

    async def stream_depth(self, symbols: Union[str, List[str]], exchange: Exchange, depth_level: int = 20):
        if isinstance(symbols, str):
            symbols = [symbols]
        instruments = [Instrument(symbol=s, exchange=exchange) for s in symbols]
        async for depth in self._broker.stream_depth(instruments, depth_level):
            yield depth

    async def stream_full(self, symbols: Union[str, List[str]], exchange: Exchange):
        if isinstance(symbols, str):
            symbols = [symbols]
        instruments = [Instrument(symbol=s, exchange=exchange) for s in symbols]
        async for pkt in self._broker.stream_full(instruments):
            yield pkt

    # -------------------------------------------------------------------------
    # Delegate everything else
    # -------------------------------------------------------------------------

    def __getattr__(self, name):
        """
        Delegate any unhandled attributes to the wrapped broker.
        This provides full access to IBrokerPort methods with circuit breaker protection.
        """
        return getattr(self._broker, name)


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
