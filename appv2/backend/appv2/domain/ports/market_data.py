"""Market Data Port — abstract interface for market data access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from appv2.domain.models.tick import Tick
from appv2.domain.models.ohlc import OHLC


class MarketDataPort(ABC):
    """Abstract interface for market data."""

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to live WebSocket feed for symbols."""

    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from symbols."""

    @abstractmethod
    async def start_stream(
        self,
        on_tick: Callable[[str, Tick], Awaitable[None]],
    ) -> None:
        """Start streaming ticks. Calls on_tick(symbol, tick) for each tick."""

    @abstractmethod
    async def stop_stream(self) -> None:
        """Stop streaming."""

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        interval: str = "1",  # minutes
        days: int = 90,
    ) -> list[OHLC]:
        """Fetch historical intraday candles from REST API."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> Tick:
        """Get latest quote (snapshot)."""

    @abstractmethod
    async def get_option_chain(
        self,
        underlying: str,
        expiry: str = "",
    ) -> list[dict]:
        """Fetch option chain from broker API."""

    @abstractmethod
    async def get_lot_size(self, symbol: str) -> int:
        """Get lot size for symbol."""
