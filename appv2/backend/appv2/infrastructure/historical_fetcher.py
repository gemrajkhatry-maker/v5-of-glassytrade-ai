"""Historical Data Fetcher — fetches intraday candles via BrokerGateway.

Uses the same gateway pattern as the original backend for broker communication.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add project root for brokers import
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from appv2.domain.models.ohlc import OHLC

logger = logging.getLogger(__name__)


class HistoricalFetcher:
    """Fetches historical intraday candles via BrokerGateway."""

    def __init__(self, access_token: str = "", client_id: str = ""):
        self._access_token = access_token
        self._client_id = client_id
        self._gateway = None

    def _ensure_gateway(self):
        if self._gateway is not None:
            return
        try:
            from brokers.gateway import BrokerGateway
            from shared.entities.models import Exchange

            if self._access_token and self._client_id:
                self._gateway = BrokerGateway.dhan(
                    client_id=self._client_id,
                    access_token=self._access_token,
                )
            else:
                self._gateway = BrokerGateway.dhan()  # Loads from env

            self._Exchange = Exchange
        except Exception as e:
            logger.error("Failed to initialize BrokerGateway: %s", e)
            self._gateway = None

    async def fetch_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1",
        days: int = 30,
    ) -> list[OHLC]:
        """Fetch historical intraday candles.

        Args:
            symbol: Symbol (e.g., "NIFTY 50", "NIFTY")
            exchange: "NSE" for index, "NFO" for futures/options
            interval: "1" for 1-min, "5" for 5-min, "15" for 15-min
            days: Number of days to fetch

        Returns:
            List of OHLC candles
        """
        self._ensure_gateway()
        if not self._gateway:
            logger.warning("Gateway unavailable — returning empty data")
            return []

        try:
            # Map exchange string to Exchange enum
            if exchange.upper() == "NFO" or "FUT" in symbol.upper():
                exch = self._Exchange.NFO
            elif exchange.upper() == "INDEX":
                exch = self._Exchange.INDEX
            else:
                exch = self._Exchange.NSE

            # Get historical data via raw broker (bypass circuit breaker)
            raw = self._gateway.raw_broker
            candles = raw.get_historical(symbol, exch, interval=interval, days=days)

            return [
                OHLC(
                    symbol=symbol,
                    time=c.get("timestamp", c.get("time", "")),
                    open=float(c.get("open", 0)),
                    high=float(c.get("high", 0)),
                    low=float(c.get("low", 0)),
                    close=float(c.get("close", 0)),
                    volume=float(c.get("volume", 0)),
                )
                for c in candles
            ]
        except Exception as e:
            logger.error("Historical fetch error for %s: %s", symbol, e)
            return []

    def fetch_candles_sync(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1",
        days: int = 30,
    ) -> list[OHLC]:
        """Synchronous version for use during startup."""
        self._ensure_gateway()
        if not self._gateway:
            return []

        try:
            if exchange.upper() == "NFO" or "FUT" in symbol.upper():
                exch = self._Exchange.NFO
            elif exchange.upper() == "INDEX":
                exch = self._Exchange.INDEX
            else:
                exch = self._Exchange.NSE

            raw = self._gateway.raw_broker
            candles = raw.get_historical(symbol, exch, interval=interval, days=days)

            return [
                OHLC(
                    symbol=symbol,
                    time=c.get("timestamp", c.get("time", "")),
                    open=float(c.get("open", 0)),
                    high=float(c.get("high", 0)),
                    low=float(c.get("low", 0)),
                    close=float(c.get("close", 0)),
                    volume=float(c.get("volume", 0)),
                )
                for c in candles
            ]
        except Exception as e:
            logger.error("Historical fetch error for %s: %s", symbol, e)
            return []

    def close(self) -> None:
        """Close gateway connection."""
        if self._gateway:
            try:
                self._gateway.close()
            except Exception:
                pass
            self._gateway = None
