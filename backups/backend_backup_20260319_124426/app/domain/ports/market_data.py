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
from typing import AsyncIterator

from app.domain.trading.models.value_objects import OHLC, OrderBook


class MarketDataPort(ABC):
    """Abstract market data provider (Dhan, simulation, etc.)."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure_initialized_sync(self, timeout: float = 120) -> None:
        """Synchronous initialization hook.

        Override in adapters that require lazy init (e.g. broker instrument
        cache loading). Default is a no-op so callers can always call safely.
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

    async def stream_poll(
        self, symbols: list[str], poll_interval: float = 3.0
    ) -> AsyncIterator[dict]:
        """REST LTP polling fallback when WS produces no data (e.g. MCX OPTFUT).

        Yields the same dict schema as stream_full() but with volume=0.
        Override in adapters that support REST quote polling.
        Default raises NotImplementedError so missing overrides are caught early.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement stream_poll()"
        )
        # Required to satisfy AsyncIterator type — never reached
        yield {}  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Options (optional override)
    # ------------------------------------------------------------------

    def get_option_chain(self, underlying: str, exchange: str = "NFO", expiry_index: int = 0):
        """Fetch option chain. Override in adapters that support options."""
        return None
