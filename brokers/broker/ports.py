"""
Broker Ports - Abstract interfaces for broker implementations.

This module defines the contract that all broker implementations must satisfy.
Each broker implementation (paper, dhan, etc.) implements these interfaces.

Design Principles:
- Interface Segregation: Separate interfaces for different concerns
- Dependency Inversion: Domain depends on abstractions, not implementations
- Single Responsibility: Each method has one clear purpose
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, AsyncIterator, Dict, Tuple, Union, runtime_checkable, Protocol
from datetime import datetime

from .entities import Instrument, Quote, Tick, Order, Position, OptionChain, Option, MarketDepth, FullPacket
from .types import Exchange
from .market_info import get_lot_size as _get_lot_size, get_step_size as _get_step_size

if TYPE_CHECKING:
    import pandas as pd
    from rx import Observable


# =============================================================================
# Circuit Breaker - Unified Implementation
# =============================================================================

import time
import asyncio
from typing import TypeVar, Awaitable, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum

T = TypeVar('T')


class CircuitState(str, Enum):
    """Circuit breaker states."""
    
    CLOSED = "closed"       # Normal operation — calls pass through
    OPEN = "open"           # Failure threshold exceeded — calls fail fast
    HALF_OPEN = "half_open" # Recovery probe — limited calls allowed through


@dataclass
class CircuitBreakerConfig:
    """
    Configuration for circuit breaker.
    
    Attributes:
        failure_threshold: Consecutive failures before tripping to OPEN.
        success_threshold: Consecutive successes in HALF_OPEN to close circuit.
        timeout: Seconds in OPEN before transitioning to HALF_OPEN.
    """
    
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout: float = 30.0  # seconds


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Unified circuit breaker supporting both sync and async patterns.
    
    Supports two usage patterns:
    
    1. Sync (context manager):
        with breaker:
            result = operation()
    
    2. Async:
        result = await breaker.execute(async_operation)
    
    States:
    - CLOSED: Normal operation, calls pass through
    - OPEN: Failure threshold exceeded, all calls fail fast
    - HALF_OPEN: Testing if service recovered
    
    Example:
        >>> breaker = CircuitBreaker(
        ...     failure_threshold=5,
        ...     recovery_timeout=60.0,
        ...     success_threshold=3
        ... )
        >>> 
        >>> # Sync usage
        >>> with breaker:
        ...     result = broker.get_quote(instrument)
        >>> 
        >>> # Async usage
        >>> result = await breaker.execute(async_operation)
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 3,
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open
            success_threshold: Successful calls in half-open to close
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()       # async path
        self._sync_lock = __import__('threading').Lock()  # sync path
        
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, transitioning OPEN→HALF_OPEN if recovery elapsed."""
        with self._sync_lock:
            self._check_and_transition()
            return self._state

    def _check_and_transition(self) -> CircuitState:
        """Transition OPEN→HALF_OPEN if recovery timeout elapsed.

        Must be called while holding _sync_lock or _lock.
        """
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
        return self._state
    
    @property
    def state_str(self) -> str:
        """Get current circuit state as string."""
        return self.state.value

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state == CircuitState.HALF_OPEN
    
    def can_execute(self) -> bool:
        """Check if execution is allowed (acquires lock for safe state check)."""
        with self._sync_lock:
            self._check_and_transition()
            return self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)
    
    def record_success(self):
        """Record a successful call (sync, thread-safe)."""
        with self._sync_lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
            else:
                self._failure_count = 0

    def record_failure(self):
        """Record a failed call (sync, thread-safe)."""
        with self._sync_lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
    
    async def record_success_async(self):
        """Record a successful call (async)."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
            else:
                self._failure_count = 0
    
    async def record_failure_async(self):
        """Record a failed call (async)."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
    
    # Sync context manager protocol (thread-safe via _sync_lock)
    def __enter__(self):
        self._sync_lock.acquire()
        self._check_and_transition()
        if self._state == CircuitState.OPEN:
            self._sync_lock.release()
            remaining = 0.0
            if self._last_failure_time:
                remaining = self.recovery_timeout - (time.time() - self._last_failure_time)
            raise CircuitBreakerError(
                f"Circuit breaker is {self.state.value}, retry in {remaining:.1f}s"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                # Inline record_success to avoid double-lock
                if self._state == CircuitState.HALF_OPEN:
                    self._success_count += 1
                    if self._success_count >= self.success_threshold:
                        self._state = CircuitState.CLOSED
                        self._failure_count = 0
                else:
                    self._failure_count = 0
            else:
                # Inline record_failure to avoid double-lock
                self._failure_count += 1
                self._last_failure_time = time.time()
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                elif self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
        finally:
            self._sync_lock.release()
        return False
    
    # Async execution
    async def execute(self, operation: Callable[[], Awaitable[T]]) -> T:
        """
        Execute an async operation through the circuit breaker.
        
        Args:
            operation: Async callable to execute
        
        Returns:
            Result of the operation
        
        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Any exception from the operation
        """
        # Check state (async path uses _lock)
        async with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.time() - (self._last_failure_time or 0)
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                else:
                    remaining = self.recovery_timeout - elapsed
                    raise CircuitBreakerError(
                        f"Circuit breaker is open, retry in {remaining:.1f}s"
                    )
        
        # Execute operation
        try:
            result = await operation()
            await self.record_success_async()
            return result
        except Exception as e:
            await self.record_failure_async()
            raise
    
    def reset(self):
        """Reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
    
    def __repr__(self) -> str:
        return f"CircuitBreaker(state={self._state.value}, failures={self._failure_count})"


# =============================================================================
# Interface Segregation Protocols
# =============================================================================

@runtime_checkable
class IMarketDataProvider(Protocol):
    """Market data retrieval interface."""
    def get_quote(self, instrument: Instrument) -> Quote: ...
    def get_quotes_batch(self, instruments: List[Instrument]) -> Dict[Instrument, Quote]: ...
    def get_historical(self, instrument: Instrument, from_date: datetime, to_date: datetime, interval: str = "1d", include_oi: bool = False) -> pd.DataFrame: ...


@runtime_checkable
class IStreamingProvider(Protocol):
    """Real-time streaming interface."""
    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]: ...
    async def stream_quotes(self, instruments: List[Instrument]) -> AsyncIterator[Quote]: ...
    async def stream_depth(self, instruments: List[Instrument], depth_level: int = 20) -> AsyncIterator[MarketDepth]: ...


@runtime_checkable
class IOrderExecutor(Protocol):
    """Order execution interface."""
    def place_order(self, order: Order) -> Order: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_order_status(self, order_id: str) -> Order: ...


@runtime_checkable
class IPortfolioProvider(Protocol):
    """Portfolio query interface."""
    def get_positions(self) -> List[Position]: ...
    def get_orderbook(self) -> List[Order]: ...


@runtime_checkable
class IOptionsProvider(Protocol):
    """Options chain interface."""
    def get_option_chain(self, underlying: str, exchange: Exchange, expiry_index: int = 0) -> OptionChain: ...
    def get_expiry_list(self, underlying: str, exchange: Exchange) -> List[datetime]: ...


# =============================================================================
# Primary Broker Port
# =============================================================================

class IBrokerPort(ABC):
    """
    Primary broker abstraction - defines the contract for all broker implementations.

    This port is the main entry point for broker operations. Implementations
    must handle all broker-specific details internally (credentials, security IDs, etc.)

    Satisfies all ISP protocol interfaces: IMarketDataProvider, IStreamingProvider,
    IOrderExecutor, IPortfolioProvider, IOptionsProvider.

    Implementations:
    - brokers/broker/paper/ - Paper trading broker
    - brokers/broker/dhan/ - DhanHQ broker
    """

    # -------------------------------------------------------------------------
    # Lifecycle — concrete no-op defaults, override as needed
    # -------------------------------------------------------------------------

    def initialize(self) -> None:
        """Initialize broker resources. Default no-op."""
        pass

    def close(self) -> None:
        """Clean up broker resources. Default no-op."""
        pass

    # -------------------------------------------------------------------------
    # Market Data - Synchronous
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_quote(self, instrument: Instrument) -> Quote:
        """
        Get current quote for instrument.

        Args:
            instrument: Instrument to get quote for

        Returns:
            Quote with current market data
        """
        pass

    @abstractmethod
    def get_quotes_batch(
        self, instruments: List[Instrument]
    ) -> Dict[Instrument, Quote]:
        """
        Get quotes for multiple instruments.

        Args:
            instruments: List of instruments to get quotes for

        Returns:
            Dict mapping instruments to their quotes
        """
        pass

    @abstractmethod
    def get_historical(
        self,
        instrument: Instrument,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        include_oi: bool = False,
    ) -> pd.DataFrame:
        """
        Get historical OHLCV data.

        Args:
            instrument: Instrument to get data for
            from_date: Start date
            to_date: End date
            interval: Time interval ("1d", "5m", "15m", etc.)
            include_oi: If True, include open interest column when supported

        Returns:
            DataFrame with OHLCV data (and optionally oi)
        """
        pass

    # -------------------------------------------------------------------------
    # Streaming - Asynchronous
    # -------------------------------------------------------------------------

    @abstractmethod
    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]:
        """
        Stream real-time ticker data.

        Args:
            instruments: Instruments to stream

        Yields:
            Tick objects as they arrive
        """
        pass

    @abstractmethod
    async def stream_quotes(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[Quote]:
        """
        Stream real-time quote data.

        Args:
            instruments: Instruments to stream

        Yields:
            Quote objects as they arrive
        """
        pass

    @abstractmethod
    async def stream_depth(
        self, instruments: List[Instrument], depth_level: int = 20
    ) -> AsyncIterator[MarketDepth]:
        """
        Stream 20-level market depth data.

        Args:
            instruments: Instruments to stream depth for
            depth_level: Number of depth levels (default 20)

        Yields:
            MarketDepth objects as they arrive
        """
        pass

    async def stream_full(self, instruments: List[Instrument]) -> AsyncIterator[FullPacket]:
        """Stream typed FULL packets (FullPacket). DhanBroker overrides for MCX support."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support stream_full")
        yield  # pragma: no cover — makes this an async generator

    # -------------------------------------------------------------------------
    # Options
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_option_chain(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain:
        """
        Get option chain for underlying.

        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            exchange: Exchange (NFO, BFO, MCX)
            expiry_index: Which expiry (0=nearest, 1=next, etc.)

        Returns:
            OptionChain with calls and puts
        """
        pass

    @abstractmethod
    def get_expiry_list(self, underlying: str, exchange: Exchange) -> List[datetime]:
        """
        Get available expiry dates.

        Args:
            underlying: Underlying symbol
            exchange: Exchange

        Returns:
            List of expiry dates
        """
        pass

    # -------------------------------------------------------------------------
    # Option Convenience Methods (string-based, no Instrument required)
    # -------------------------------------------------------------------------

    def find_atm_options(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> Tuple[Optional[Option], Optional[Option], float]:
        """
        Find ATM call and put options for an underlying.

        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            exchange: Exchange (NFO, BFO, MCX)
            expiry_index: Which expiry (0=nearest)

        Returns:
            Tuple of (ATM CE, ATM PE, ATM strike)
        """
        chain = self.get_option_chain(underlying, exchange, expiry_index)
        ce, pe = chain.get_atm_options()
        return ce, pe, chain.atm_strike

    def find_otm_options(
        self, underlying: str, exchange: Exchange, distance: int = 1, expiry_index: int = 0
    ) -> Tuple[Optional[Option], Optional[Option], float, float]:
        """
        Find OTM call and put options.

        OTM Call = ATM + (distance * step_size)
        OTM Put  = ATM - (distance * step_size)

        Args:
            underlying: Underlying symbol
            exchange: Exchange
            distance: Number of steps from ATM (default 1)
            expiry_index: Which expiry (0=nearest)

        Returns:
            Tuple of (OTM CE, OTM PE, CE strike, PE strike)
        """
        chain = self.get_option_chain(underlying, exchange, expiry_index)
        ce, pe = chain.get_otm_options(distance)
        ce_strike = chain.atm_strike + (distance * chain.step_size)
        pe_strike = chain.atm_strike - (distance * chain.step_size)
        return ce, pe, ce_strike, pe_strike

    def find_itm_options(
        self, underlying: str, exchange: Exchange, distance: int = 1, expiry_index: int = 0
    ) -> Tuple[Optional[Option], Optional[Option], float, float]:
        """
        Find ITM call and put options.

        ITM Call = ATM - (distance * step_size)
        ITM Put  = ATM + (distance * step_size)

        Args:
            underlying: Underlying symbol
            exchange: Exchange
            distance: Number of steps from ATM (default 1)
            expiry_index: Which expiry (0=nearest)

        Returns:
            Tuple of (ITM CE, ITM PE, CE strike, PE strike)
        """
        chain = self.get_option_chain(underlying, exchange, expiry_index)
        ce, pe = chain.get_itm_options(distance)
        ce_strike = chain.atm_strike - (distance * chain.step_size)
        pe_strike = chain.atm_strike + (distance * chain.step_size)
        return ce, pe, ce_strike, pe_strike

    def get_lot_size(self, underlying: str) -> int:
        """
        Get lot size for an underlying.

        Args:
            underlying: Symbol (e.g., "NIFTY", "BANKNIFTY", "GOLD")

        Returns:
            Lot size (quantity per lot). Returns 1 if not found.
        """
        return _get_lot_size(underlying)

    def get_step_size(self, underlying: str) -> float:
        """
        Get strike step size for an underlying.

        Args:
            underlying: Symbol (e.g., "NIFTY", "BANKNIFTY")

        Returns:
            Step size. Returns 5.0 as default for stocks.
        """
        return _get_step_size(underlying)

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    @abstractmethod
    def place_order(self, order: Order) -> Order:
        """
        Place a new order.

        Args:
            order: Order to place

        Returns:
            Order with updated status and order_id
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Order:
        """
        Get current order status.

        Args:
            order_id: Order ID

        Returns:
            Order with current status
        """
        pass

    # -------------------------------------------------------------------------
    # Portfolio
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """
        Get all open positions.

        Returns:
            List of open positions
        """
        pass

    @abstractmethod
    def get_orderbook(self) -> List[Order]:
        """
        Get all orders.

        Returns:
            List of orders
        """
        pass


class IReactiveBroker(ABC):
    """
    Reactive broker interface for event-driven architectures.

    Provides Observables for market data streams. Use this for
    reactive programming patterns.
    """

    @abstractmethod
    def ticker_stream(self, instruments: List[Instrument]) -> Observable[Tick]:
        """Observable of ticker updates."""
        pass

    @abstractmethod
    def quote_stream(self, instruments: List[Instrument]) -> Observable[Quote]:
        """Observable of quote updates."""
        pass

    @abstractmethod
    def depth_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = None,
        depth_level: int = 20,
    ) -> Observable[MarketDepth]:
        """
        Observable of market depth updates.

        depth_level=20  → dedicated 20-level depth feed (up to 50 instruments)
        depth_level=200 → dedicated 200-level depth feed (1 instrument only)
        depth_level=5   → 5-level depth via regular market feed

        Each emission is a MarketDepth for one side (bid or ask).
        """
        pass

    @abstractmethod
    def depth_20_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = None,
    ) -> Observable[MarketDepth]:
        """
        Observable of 20-level market depth via the dedicated depth feed.

        Equivalent to depth_stream(symbols, exchange, depth_level=20).
        Supports up to 50 NSE instruments per subscription.
        Each emission is a MarketDepth for one side (bid or ask).
        """
        pass

    @abstractmethod
    def depth_200_stream(
        self,
        symbol: Union[str, Instrument],
        exchange: Exchange = None,
    ) -> Observable[MarketDepth]:
        """
        Observable of 200-level market depth via the full-depth feed.

        Only 1 instrument per connection (Dhan server limit).
        Each emission is a MarketDepth for one side (bid or ask).
        """
        pass

    @abstractmethod
    def order_update_stream(self) -> Observable[Order]:
        """Observable of order status updates."""
        pass

    @abstractmethod
    def position_update_stream(self) -> Observable[Position]:
        """Observable of position changes."""
        pass

    @abstractmethod
    def historical_stream(
        self,
        symbol: Union[str, Instrument],
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        exchange: Exchange = None,
        include_oi: bool = False,
    ) -> Observable[Dict]:
        """
        Observable of historical OHLCV candles for a single symbol.

        Fetches data synchronously and emits each candle as a dict.
        Completes after all candles have been emitted.

        Returns:
            Observable[Dict] — keys: open, high, low, close, volume, timestamp
                               (plus oi if include_oi=True and broker supports it)
        """
        pass

    @abstractmethod
    def bulk_historical_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        exchange: Exchange = None,
    ) -> Observable[Tuple[str, Dict]]:
        """
        Observable of historical candles for multiple symbols.

        Emits (symbol_name, candle_dict) tuples, symbol by symbol, then completes.

        Returns:
            Observable[Tuple[str, Dict]] — (symbol, candle_dict) per row
        """
        pass

    @abstractmethod
    def option_chain_stream(
        self,
        underlying: str,
        exchange: Exchange = None,
        expiry_index: int = 0,
        refresh_interval: float = 5.0,
    ) -> Observable[OptionChain]:
        """
        Periodic option chain snapshots.

        Polls the broker and emits a fresh OptionChain at each interval.

        Returns:
            Observable[OptionChain]
        """
        pass

    @abstractmethod
    def atm_strike_stream(
        self,
        underlying: str,
        exchange: Exchange = None,
        expiry_index: int = 0,
        refresh_interval: float = 5.0,
    ) -> Observable[float]:
        """
        Emits the ATM strike whenever it changes.

        Returns:
            Observable[float] — distinct ATM strike values
        """
        pass

    @abstractmethod
    def spot_price_stream(
        self,
        underlying: str,
        exchange: Exchange = None,
        expiry_index: int = 0,
        refresh_interval: float = 2.0,
    ) -> Observable[float]:
        """
        Continuous spot price updates polled from the option chain.

        Returns:
            Observable[float]
        """
        pass

    @abstractmethod
    def option_oi_stream(
        self,
        underlying: str,
        strike: float,
        option_type: str = "CE",
        exchange: Exchange = None,
        expiry_index: int = 0,
        refresh_interval: float = 5.0,
    ) -> Observable[int]:
        """
        Open Interest updates for a specific option strike.

        Returns:
            Observable[int] — OI value per poll cycle
        """
        pass

    @abstractmethod
    def option_chain_diff_stream(
        self,
        underlying: str,
        exchange: Exchange = None,
        expiry_index: int = 0,
        refresh_interval: float = 5.0,
    ) -> Observable[Dict]:
        """
        Incremental OI/volume/spot changes between option chain snapshots.

        Returns:
            Observable[Dict] — keys: spot, spot_change, atm, oi_changes, volume_changes
        """
        pass


@runtime_checkable
class IAsyncOptionChainProvider(Protocol):
    """
    Protocol for brokers that support async option chain fetching.

    Brokers implementing this protocol can be detected via isinstance()
    instead of hasattr(), satisfying the Open/Closed Principle.
    """

    async def get_option_chain_async(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain: ...


# =============================================================================
# Circuit Breaker Wrapper
# =============================================================================

class CircuitBreakerWrapper:
    """
    Wraps an IBrokerPort with circuit breaker protection.
    
    This wrapper adds fault tolerance to any broker implementation without
    requiring the broker to implement circuit breaker logic itself.
    
    The wrapper implements IBrokerPort and can be used as a drop-in replacement.
    
    Example:
        >>> broker = DhanBroker.create(...)
        >>> breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        >>> wrapped = CircuitBreakerWrapper(broker, breaker)
        >>> 
        >>> # Use wrapped broker exactly like the original
        >>> quote = wrapped.get_quote(instrument)
    """
    
    def __init__(
        self,
        broker: IBrokerPort,
        circuit_breaker: CircuitBreaker,
    ):
        """
        Initialize wrapper with broker and circuit breaker.
        
        Args:
            broker: The broker to wrap
            circuit_breaker: Circuit breaker for fault tolerance
        """
        self._broker = broker
        self._breaker = circuit_breaker
    
    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access the circuit breaker."""
        return self._breaker
    
    @property
    def broker(self) -> IBrokerPort:
        """Access the underlying broker."""
        return self._broker
    
    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    
    def initialize(self) -> None:
        """Initialize the underlying broker."""
        self._broker.initialize()
    
    def close(self) -> None:
        """Close the underlying broker."""
        self._broker.close()
    
    # -------------------------------------------------------------------------
    # Market Data - Synchronous (wrapped with circuit breaker)
    # -------------------------------------------------------------------------
    
    def get_quote(self, instrument: Instrument) -> Quote:
        """Get quote with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_quote(instrument)
    
    def get_quotes_batch(self, instruments: List[Instrument]) -> Dict[Instrument, Quote]:
        """Get batch quotes with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_quotes_batch(instruments)
    
    def get_historical(
        self,
        instrument: Instrument,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        include_oi: bool = False,
    ):
        """Get historical data with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_historical(instrument, from_date, to_date, interval, include_oi)
    
    # -------------------------------------------------------------------------
    # Streaming - Asynchronous
    # -------------------------------------------------------------------------
    
    async def stream_ticker(self, instruments: List[Instrument]):
        """Stream ticker data (passthrough - async iterators can't be easily wrapped)."""
        async for tick in self._broker.stream_ticker(instruments):
            yield tick
    
    async def stream_quotes(self, instruments: List[Instrument]):
        """Stream quotes (passthrough)."""
        async for quote in self._broker.stream_quotes(instruments):
            yield quote
    
    async def stream_depth(self, instruments: List[Instrument], depth_level: int = 20):
        """Stream depth (passthrough)."""
        async for depth in self._broker.stream_depth(instruments, depth_level):
            yield depth
    
    async def stream_full(self, instruments: List[Instrument]):
        """Stream full packets (passthrough)."""
        async for pkt in self._broker.stream_full(instruments):
            yield pkt
    
    # -------------------------------------------------------------------------
    # Options
    # -------------------------------------------------------------------------
    
    def get_option_chain(self, underlying: str, exchange: Exchange, expiry_index: int = 0) -> OptionChain:
        """Get option chain with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_option_chain(underlying, exchange, expiry_index)
    
    def get_expiry_list(self, underlying: str, exchange: Exchange) -> List[datetime]:
        """Get expiry list with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_expiry_list(underlying, exchange)
    
    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------
    
    def place_order(self, order: Order) -> Order:
        """Place order with circuit breaker protection."""
        with self._breaker:
            return self._broker.place_order(order)
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order with circuit breaker protection."""
        with self._breaker:
            return self._broker.cancel_order(order_id)
    
    def get_order_status(self, order_id: str) -> Order:
        """Get order status with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_order_status(order_id)
    
    # -------------------------------------------------------------------------
    # Portfolio
    # -------------------------------------------------------------------------
    
    def get_positions(self) -> List[Position]:
        """Get positions with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_positions()
    
    def get_orderbook(self) -> List[Order]:
        """Get orderbook with circuit breaker protection."""
        with self._breaker:
            return self._broker.get_orderbook()
    
    def __repr__(self) -> str:
        return f"CircuitBreakerWrapper(broker={self._broker!r}, breaker={self._breaker!r})"
