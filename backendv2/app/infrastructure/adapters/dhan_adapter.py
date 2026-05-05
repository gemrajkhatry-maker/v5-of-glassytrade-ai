"""Dhan adapter (broker + market data) for production and tests.

Implements both legacy broker order methods and the domain ``IMarketData`` port.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator

import httpx

from app.domain.shared.port.market_data import IMarketData
from app.domain.shared.timezones import IST
from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.dhan.co"


class DhanAdapter(IMarketData):
    """Adapter that supports live and paper-compatible market data adapters."""

    def __init__(
        self,
        symbols: list[str] | None = None,
        exchange: str | None = None,
        client_id: str | None = None,
        access_token: str | None = None,
        base_url: str | None = None,
        testnet: bool = True,
        timeout: float = 20.0,
    ) -> None:
        self._symbols = symbols or []
        self._exchange = exchange
        self._client_id = client_id
        self._access_token = access_token
        self._testnet = testnet
        self._base_url = base_url or _DEFAULT_BASE_URL
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "access-token": str(access_token or ""),
                "x-client-id": str(client_id or ""),
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self._is_ready = False
        self._lot_cache: dict[str, int] = {}
        self._ltp_cache: dict[str, tuple[float, float]] = {}
        self._order_books: dict[str, OrderBook] = {}
        self._stream_offsets: deque[float] = deque(maxlen=1024)

    def ensure_initialized_sync(self, timeout: float = 120) -> None:
        self._is_ready = True

    async def _ensure_initialized(self) -> None:
        if not self._is_ready:
            self._is_ready = True

    def close_sync(self) -> None:
        if getattr(self._client, "is_closed", False):
            return
        self._client.close()

    async def close(self):
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Broker-style methods used by integration tests / legacy paths
    # ------------------------------------------------------------------
    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict:
        payload = {
            "tradingsymbol": symbol,
            "exchange": self._exchange or "NSE",
            "transactiontype": side,
            "quantity": int(qty),
            "ordertype": "MARKET" if float(price) <= 0 else "LIMIT",
            "producttype": "INTRADAY",
            "price": float(price),
        }
        if not self._access_token:
            return {
                "order_id": f"{symbol}_{asyncio.get_event_loop().time()}",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": float(price),
                "status": "DUMMY",
            }

        response = await self._client.post("/v2/orders", json=payload)
        response.raise_for_status()
        data = self._safe_json(response, {})
        return {
            "order_id": data.get("orderId", f"{symbol}_{asyncio.get_event_loop().time()}"),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": float(price),
            "status": data.get("status", "PENDING"),
        }

    async def cancel_order(self, order_id: str) -> bool:
        if not self._access_token:
            return True
        try:
            response = await self._client.delete(f"/v2/orders/{order_id}")
            response.raise_for_status()
            return True
        except Exception:
            return False

    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        if not self._access_token:
            return None
        response = await self._client.get("/v2/holdings")
        response.raise_for_status()
        holdings = self._safe_json(response, [])
        for holding in holdings:
            if str(holding.get("tradingSymbol", "")).upper() == symbol.upper():
                return {
                    "symbol": symbol,
                    "quantity": Decimal(str(holding.get("netQty", 0))),
                    "avg_price": Decimal(str(holding.get("avgCostPrice", 0))),
                    "pnl": Decimal(str(holding.get("pnl", 0))),
                }
        return None

    async def close_position(self, order_id: str, price: float) -> bool:
        return await self.cancel_order(order_id)

    # ------------------------------------------------------------------
    # IMarketData methods used by runtime
    # ------------------------------------------------------------------
    async def scan_candidates(self, limit: int = 6) -> list[str]:
        return self._symbols[:limit]

    async def fetch_history(self, symbol: str, interval: str = "5m", limit: int = 500) -> list[OHLC]:
        await self._ensure_initialized()
        if not self._access_token:
            return []
        params = {
            "symbol": symbol,
            "exchange": self._exchange or "NSE",
            "interval": interval,
            "from": datetime.now(tz=IST).isoformat(),
            "limit": limit,
        }
        response = await self._client.get("/api/charts/historical", params=params)
        if response.status_code != 200:
            return []
        payload = self._safe_json(response, [])
        if not isinstance(payload, list):
            return []
        out: list[OHLC] = []
        for item in payload[-limit:]:
            open_ = float(item.get("open", 0.0))
            high = float(item.get("high", 0.0))
            low = float(item.get("low", 0.0))
            close = float(item.get("close", 0.0))
            volume = float(item.get("volume", 0.0))
            ts = item.get("time", "")
            vwap = float(item.get("vwap", (open_ + high + low + close) / 4))
            out.append(
                OHLC(
                    time=str(ts),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    vwap=vwap,
                    taker_buy_volume=float(item.get("takerBuyVolume", 0.0)),
                    delta=float(item.get("delta", 0.0)),
                )
            )
        return out

    async def fetch_order_book(self, symbol: str) -> OrderBook | None:
        await self._ensure_initialized()
        if not self._access_token:
            return None
        response = await self._client.get(
            "/api/order-book",
            params={"symbol": symbol, "exchange": self._exchange or "NSE"},
        )
        if response.status_code != 200:
            return None
        payload = self._safe_json(response, {})
        if not isinstance(payload, dict):
            return None
        bids = [
            OrderBookLevel(price=float(item.get("price", 0.0)), quantity=float(item.get("quantity", 0.0)))
            for item in payload.get("bids", [])[:50]
            if float(item.get("price", 0.0)) > 0
        ]
        asks = [
            OrderBookLevel(price=float(item.get("price", 0.0)), quantity=float(item.get("quantity", 0.0)))
            for item in payload.get("asks", [])[:50]
            if float(item.get("price", 0.0)) > 0
        ]
        ob = OrderBook(bids=tuple(bids), asks=tuple(asks))
        self._order_books[symbol] = ob
        return ob

    def get_ltp(self, symbol: str) -> float:
        if not self._access_token:
            return self._ltp_cache.get(symbol, (0.0, 0.0))[0]
        try:
            asyncio.get_running_loop()
            return self._ltp_cache.get(symbol, (0.0, 0.0))[0]
        except RuntimeError:
            pass
        response = asyncio.get_event_loop().run_until_complete(
            self._client.get(
                "/api/ltp",
                params={"symbol": symbol, "exchange": self._exchange or "NSE"},
            )
        )
        if response.status_code != 200:
            return self._ltp_cache.get(symbol, (0.0, 0.0))[0]
        payload = self._safe_json(response, {})
        try:
            ltp = float(payload.get("ltp", 0.0))
        except Exception:
            ltp = 0.0
        if ltp > 0:
            self._ltp_cache[symbol] = (ltp, datetime.now(tz=IST).timestamp())
            return ltp
        return self._ltp_cache.get(symbol, (0.0, 0.0))[0]

    def get_lot_size(self, symbol: str) -> int:
        if cached := self._lot_cache.get(symbol):
            return cached
        return 1

    async def stream_full(self, symbols: list[str]) -> AsyncIterator[dict]:
        interval = float(os.getenv("DHAN_STREAM_INTERVAL", "1.5"))
        while True:
            now_ts = datetime.now(tz=IST).isoformat()
            for symbol in symbols:
                ltp = self.get_ltp(symbol)
                if ltp <= 0:
                    continue
                self._stream_offsets.append(ltp)
                yield {
                    "symbol": symbol,
                    "ltp": ltp,
                    "timestamp": now_ts,
                    "volume": 0,
                    "ltq": 0,
                    "oi": 0,
                    "total_buy_qty": 0,
                    "total_sell_qty": 0,
                    "depth_bids": [],
                    "depth_asks": [],
                }
            await asyncio.sleep(interval)

    async def stream_depth_20(self, symbols: list[str]) -> AsyncIterator[dict]:
        async for tick in self.stream_full(symbols):
            ob = await self.fetch_order_book(tick["symbol"])
            if ob is None:
                yield {
                    "symbol": tick["symbol"],
                    "bids": [],
                    "asks": [],
                    "timestamp": tick.get("timestamp"),
                }
            else:
                yield {
                    "symbol": tick["symbol"],
                    "bids": [{"price": b.price, "quantity": b.quantity} for b in ob.bids[:20]],
                    "asks": [{"price": a.price, "quantity": a.quantity} for a in ob.asks[:20]],
                    "timestamp": tick.get("timestamp"),
                }

    def get_option_chain(self, underlying: str, exchange: str = "NFO", expiry_index: int = 0):
        if not self._access_token:
            return None
        try:
            asyncio.get_running_loop()
            return None
        except RuntimeError:
            pass
        response = asyncio.get_event_loop().run_until_complete(
            self._client.get(
                "/api/options/chain",
                params={
                    "underlying": underlying,
                    "exchange": exchange,
                    "expiry_index": expiry_index,
                },
            )
        )
        if response.status_code != 200:
            return None
        return self._safe_json(response, None)

    def _safe_json(self, response: Any, fallback: Any | None = None) -> Any:
        try:
            return response.json()
        except Exception:
            return fallback if fallback is not None else {}
