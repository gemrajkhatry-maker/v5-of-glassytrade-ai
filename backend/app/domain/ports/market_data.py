"""MarketData port — abstract interface for market data retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.trading.models.value_objects import OHLC, OrderBook


class MarketDataPort(ABC):
    """Abstract market data provider (Binance, simulation, etc.)."""

    @abstractmethod
    async def scan_candidates(self, limit: int = 6) -> list[str]:
        """Scan for high-volume trading candidates."""
        ...

    @abstractmethod
    async def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 500
    ) -> list[OHLC]:
        """Fetch historical OHLCV data."""
        ...

    @abstractmethod
    async def fetch_order_book(self, symbol: str) -> OrderBook | None:
        """Fetch the current L2 order book snapshot."""
        ...
