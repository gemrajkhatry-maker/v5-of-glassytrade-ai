"""MarketData port — abstract interface for market data retrieval.

Error contracts:
    - fetch_history(): returns [] for no data, raises for API failure
    - get_ltp(): returns 0.0 for no data, raises for API failure
    - fetch_order_book(): returns None for no depth, raises for API failure
    - get_option_chain(): returns None by default (override for options support)
    - stream_full(): async generator of dicts; raises on connection failure
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from app.domain.trading.models.value_objects import OHLC, OrderBook


class IMarketData(ABC):
    """Abstract market data provider (Dhan, simulation, etc.)."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_initialized_sync(self, timeout: float = 120) -> None:
        """Synchronous initialization hook.

        Override in adapters that require lazy init (e.g. broker instrument
        cache loading). Default is a no-op so callers can always call safely.
        """

    def close_sync(self) -> None:
        """Shutdown hook — releases all connections and background tasks.

        Override in adapters that hold persistent network resources
        (e.g. Dhan WebSocket). Default is a no-op.
        """

    # ------------------------------------------------------------------
    # Market data queries
    # ------------------------------------------------------------------

    @abstractmethod
    async def scan_candidates(self, limit: int = 6) -> list[str]:
        """Scan for high-volume trading candidates."""
        ...

    @abstractmethod
    async def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 500
    ) -> list[OHLC]:
        """Fetch historical OHLCV data.

        Returns:
            List of OHLC candles, empty list if no data available.
        Raises:
            Exception on API/connection failure.
        """
        ...

    @abstractmethod
    async def fetch_order_book(self, symbol: str) -> OrderBook | None:
        """Fetch the current L2 order book snapshot.

        Returns:
            OrderBook if depth available, None otherwise.
        Raises:
            Exception on API/connection failure.
        """
        ...

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Get last traded price (synchronous).

        Returns:
            Last traded price, 0.0 if unavailable.
        Raises:
            Exception on API/connection failure.
        """
        ...

    # ------------------------------------------------------------------
    # Live streaming
    # ------------------------------------------------------------------

    @abstractmethod
    async def stream_full(self, symbols: list[str]) -> AsyncIterator[dict]:
        """Stream live tick data (LTP, volume, depth, OHLC, OI).

        Yields dicts with keys: ltp, volume, oi, timestamp,
        depth_bids, depth_asks, open, high, low, close, etc.
        Raises on connection failure.
        """
        ...

    @abstractmethod
    async def stream_depth_20(self, symbols: list[str]) -> AsyncIterator[Any]:
        """Stream 20-level market depth order book updates."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement stream_depth_20()"
        )  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Options (optional override)
    # ------------------------------------------------------------------

    def get_option_chain(self, underlying: str, exchange: str = "NFO", expiry_index: int = 0):
        """Fetch option chain. Override in adapters that support options."""
        return None

    def get_lot_size(self, symbol: str) -> int:
        """Get the lot size for a specific symbol.

        Returns:
            Lot size (default 1 for equities).
        """
        return 1
