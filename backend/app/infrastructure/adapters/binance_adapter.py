"""Binance market data adapter — implements MarketDataPort using httpx.

This is the concrete infrastructure adapter for Binance REST API.
Domain objects (OHLC, OrderBook) are returned directly — no Pydantic DTOs
at this boundary.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
from app.domain.ports.market_data import MarketDataPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMMON_BASES = {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB"}
_EXCLUDE = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT"}


def normalize_symbol(symbol: str) -> str:
    """Normalise a user-entered symbol to Binance format."""
    s = re.sub(r"[^a-zA-Z0-9]", "", symbol).upper()
    if s in _COMMON_BASES:
        return s + "USDT"
    if len(s) <= 4 and not s.endswith("USDT") and not s.endswith("BTC"):
        return s + "USDT"
    return s


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class BinanceMarketDataAdapter(MarketDataPort):
    """Binance REST API adapter."""

    def __init__(self, base_url: str = "https://api.binance.com") -> None:
        self._base_url = base_url

    async def scan_candidates(self, limit: int = 6) -> list[str]:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"{self._base_url}/api/v3/ticker/24hr", timeout=15,
                )
                res.raise_for_status()
                data = res.json()

            candidates = [
                t["symbol"]
                for t in sorted(data, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
                if (
                    t["symbol"].endswith("USDT")
                    and "UPUSDT" not in t["symbol"]
                    and "DOWNUSDT" not in t["symbol"]
                    and t["symbol"] not in _EXCLUDE
                )
            ][:limit]

            return candidates if candidates else ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        except Exception:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    async def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 500
    ) -> list[OHLC]:
        try:
            clean = normalize_symbol(symbol)
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"{self._base_url}/api/v3/klines",
                    params={"symbol": clean, "interval": interval, "limit": limit},
                    timeout=15,
                )
                res.raise_for_status()
                data = res.json()

            result: list[OHLC] = []
            for d in data:
                volume = float(d[5])
                quote_volume = float(d[7])
                taker_buy = float(d[9])
                vwap = quote_volume / volume if volume > 0 else (float(d[1]) + float(d[4])) / 2
                delta = (2 * taker_buy) - volume
                time_str = datetime.fromtimestamp(d[0] / 1000, tz=timezone.utc).isoformat()

                result.append(OHLC(
                    time=time_str, open=float(d[1]), high=float(d[2]),
                    low=float(d[3]), close=float(d[4]), volume=volume,
                    vwap=vwap, taker_buy_volume=taker_buy, delta=delta,
                ))
            return result
        except Exception:
            return []

    async def fetch_order_book(self, symbol: str) -> OrderBook | None:
        try:
            clean = normalize_symbol(symbol)
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"{self._base_url}/api/v3/depth",
                    params={"symbol": clean, "limit": 50},
                    timeout=10,
                )
                res.raise_for_status()
                data = res.json()

            return OrderBook(
                bids=tuple(OrderBookLevel(price=float(b[0]), quantity=float(b[1])) for b in data["bids"]),
                asks=tuple(OrderBookLevel(price=float(a[0]), quantity=float(a[1])) for a in data["asks"]),
            )
        except Exception:
            return None
