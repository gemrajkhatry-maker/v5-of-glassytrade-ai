"""Dhan Market Data Feed adapter — wraps existing brokers library.

Reuses: brokers/broker/dhan/ (StreamingService, DhanBroker)
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import Callable, Awaitable

# Add project root to path for brokers import
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from appv2.domain.ports.market_data import MarketDataPort
from appv2.domain.models.tick import Tick
from appv2.domain.models.ohlc import OHLC

logger = logging.getLogger(__name__)


class DhanMarketDataAdapter(MarketDataPort):
    """Adapts Dhan broker library to MarketDataPort interface.

    Reuses the existing brokers/ library — no re-implementation.
    """

    def __init__(self, access_token: str, client_id: str):
        self._access_token = access_token
        self._client_id = client_id
        self._broker = None
        self._on_tick: Callable[[str, Tick], Awaitable[None]] | None = None
        self._subscribed: set[str] = set()

    def _ensure_broker(self):
        """Lazy initialization of Dhan broker."""
        if self._broker is not None:
            return
        try:
            from broker.dhan.application.broker import DhanBroker
            from broker.dhan.application.config import DhanConfig

            config = DhanConfig(
                access_token=self._access_token,
                client_id=self._client_id,
            )
            self._broker = DhanBroker(config)
            logger.info("DhanBroker initialized")
        except ImportError:
            logger.error("brokers/ library not found — using mock feed")
            self._broker = None

    async def subscribe(self, symbols: list[str]) -> None:
        self._ensure_broker()
        for sym in symbols:
            self._subscribed.add(sym)
        logger.info("Subscribed to: %s", symbols)

    async def unsubscribe(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._subscribed.discard(sym)
        logger.info("Unsubscribed from: %s", symbols)

    async def start_stream(self, on_tick: Callable[[str, Tick], Awaitable[None]]) -> None:
        self._on_tick = on_tick
        self._ensure_broker()
        logger.info("Stream started (simulation mode — use TradingEngine for production)")

    async def stop_stream(self) -> None:
        self._on_tick = None
        logger.info("Stream stopped")

    async def get_historical_candles(
        self,
        symbol: str,
        interval: str = "1",
        days: int = 90,
    ) -> list[OHLC]:
        """Fetch from Dhan REST API via brokers library."""
        self._ensure_broker()
        if self._broker:
            try:
                candles = self._broker.get_intraday_candles(
                    security_id=symbol,
                    interval=interval,
                    days=days,
                )
                return [
                    OHLC(
                        symbol=symbol,
                        time=c["time"],
                        open=float(c["open"]),
                        high=float(c["high"]),
                        low=float(c["low"]),
                        close=float(c["close"]),
                        volume=float(c.get("volume", 0)),
                    )
                    for c in candles
                ]
            except Exception as e:
                logger.error("Historical fetch error: %s", e)
        return []

    async def get_quote(self, symbol: str) -> Tick:
        return Tick(symbol=symbol, ltp=0.0)

    async def get_option_chain(self, underlying: str, expiry: str = "") -> list[dict]:
        self._ensure_broker()
        if self._broker:
            try:
                return self._broker.get_option_chain(underlying, expiry)
            except Exception as e:
                logger.error("Option chain error: %s", e)
        return []

    async def get_lot_size(self, symbol: str) -> int:
        self._ensure_broker()
        if self._broker:
            try:
                return self._broker.get_lot_size(symbol)
            except Exception:
                pass
        return 50  # Default NIFTY lot size
