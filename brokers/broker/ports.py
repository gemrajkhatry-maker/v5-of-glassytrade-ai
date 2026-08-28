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

from shared.resilience import (
    CircuitState,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreaker,
)


# =============================================================================
# Primary Broker Port
# =============================================================================

class IBrokerPort(ABC):
    """
    Primary broker abstraction - defines the contract for all broker implementations.

    This port is the main entry point for broker operations. Implementations
    must handle all broker-specific details internally (credentials, security IDs, etc.)

    Implementations:
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


