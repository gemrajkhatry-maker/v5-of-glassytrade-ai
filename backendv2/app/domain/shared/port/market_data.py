"""MarketData port — abstract interface for market data retrieval.

Domain defines this port. Infrastructure provides the adapter.

Error contracts:
    - fetch_history(): returns [] for no data, raises for API failure
    - get_ltp(): returns 0.0 for no data, raises for API failure
    - fetch_order_book(): returns None for no depth, raises for API failure
    - get_option_chain(): must be implemented by option-capable adapters
    - stream_full(): async generator of dicts; raises on connection failure
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from app.domain.trading.model.value_objects import OHLC, OrderBook


class IMarketData(ABC):
    """Abstract market data provider (Dhan, simulation, etc.)."""

    def ensure_initialized_sync(self, timeout: float = 120) -> None:
        """Synchronous initialization hook. Default is a no-op."""
        ...

    def close_sync(self) -> None:
        """Shutdown hook. Default is a no-op."""
        ...

    @abstractmethod
    async def scan_candidates(self, limit: int = 6) -> list[str]:
        """Scan for high-volume trading candidates."""
        ...

    @abstractmethod
    async def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 500
    ) -> list[OHLC]:
        """Fetch historical OHLCV data. Returns [] for no data, raises on failure."""
        ...

    @abstractmethod
    async def fetch_order_book(self, symbol: str) -> OrderBook | None:
        """Fetch the current L2 order book snapshot."""
        ...

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Get last traded price (synchronous)."""
        ...

    @abstractmethod
    async def stream_full(self, symbols: list[str]) -> AsyncIterator[dict]:
        """Stream live tick data (LTP, volume, depth, OHLC, OI)."""
        ...

    @abstractmethod
    async def stream_depth_20(self, symbols: list[str]) -> AsyncIterator[Any]:
        """Stream 20-level market depth order book updates."""
        ...

    @abstractmethod
    def get_option_chain(self, underlying: str, exchange: str = "NFO", expiry_index: int = 0):
        """Fetch option chain. Implement in options-capable adapters."""
        raise NotImplementedError

    @abstractmethod
    def get_lot_size(self, symbol: str) -> int:
        """Get the lot size for a specific symbol."""
        raise NotImplementedError
