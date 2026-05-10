"""Dhan adapter (broker + market data) for production and tests.

Implements both legacy broker order methods and the domain ``IMarketData`` port.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, AsyncIterator

import httpx

from app.domain.shared.port.market_data import IMarketData
from app.shared.timezones import IST
from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel
from app.infrastructure.adapters.option_chain_cache import OptionChainCache

try:
    from app.core.cost_tracker import get_cost_tracker
    _HAS_COST_TRACKING = True
except ImportError:
    _HAS_COST_TRACKING = False

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
        self._option_chain_cache = OptionChainCache(
            ttl_sec=float(os.getenv("OPTION_CHAIN_CACHE_TTL_SEC", "30") or 30)
        )

    def ensure_initialized_sync(self, timeout: float = 120) -> None:
        self._is_ready = True

    async def _ensure_initialized(self) -> None:
        if not self._is_ready:
            self._is_ready = True

    def close_sync(self) -> None:
        if getattr(self._client, "is_closed", False):
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
            return
        self._run_sync(self._client.aclose())

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
        data = _safe_json(response, {})
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
        holdings = _safe_json(response, [])
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
        from app.domain.fabio_ai.services.option_scanner import OptionScannerService

        default_exchange = self._exchange or os.getenv("DEFAULT_EXCHANGE", "NSE")
        default_underlyings = self._symbols or [u.strip() for u in os.getenv("SCANNER_UNDERLYINGS", "NIFTY,BANKNIFTY,FINNIFTY").split(",") if u.strip()]
        try:
            scanner = OptionScannerService(self, default_underlyings=default_underlyings)
            top_n = max(1, int(os.getenv("SCANNER_TOP_N", "4")))
            top_per_underlying = max(1, int(os.getenv("SCANNER_TOP_PER_UNDERLYING", "2")))
            strikes_around_atm = max(1, int(os.getenv("SCANNER_STRIKES_AROUND_ATM", "1")))
            results = await asyncio.to_thread(
                scanner.scan_top_n,
                n=top_n,
                exchange=default_exchange,
                underlyings=default_underlyings,
                top_per_underlying=top_per_underlying,
                strikes_around_atm=strikes_around_atm,
            )
            return [r.symbol for r in results[:limit]]
        except Exception:
            logger.exception("scan_candidates failed; falling back to configured symbols")
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
        payload = _safe_json(response, [])
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
        payload = _safe_json(response, {})
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
            return self._cached_ltp(symbol)
        try:
            asyncio.get_running_loop()
            return self._cached_ltp(symbol)
        except RuntimeError:
            pass
        t0 = time.time()
        try:
            response = asyncio.get_event_loop().run_until_complete(
                self._client.get(
                    "/api/ltp",
                    params={"symbol": symbol, "exchange": self._exchange or "NSE"},
                )
            )
            latency = (time.time() - t0) * 1000
            status = "ok" if response.status_code == 200 else "error"
            if _HAS_COST_TRACKING:
                get_cost_tracker().record_api_call("/api/ltp", symbol, latency, status)
            if response.status_code != 200:
                return self._cached_ltp(symbol)
            payload = _safe_json(response, {})
            try:
                ltp = float(payload.get("ltp", 0.0))
            except Exception:
                ltp = 0.0
            if ltp > 0:
                self._ltp_cache[symbol] = (datetime.now(tz=IST).timestamp(), ltp)
                return ltp
            return self._cached_ltp(symbol)
        except Exception:
            latency = (time.time() - t0) * 1000
            if _HAS_COST_TRACKING:
                get_cost_tracker().record_api_call("/api/ltp", symbol, latency, "error")
            return self._cached_ltp(symbol)

    def _cached_ltp(self, symbol: str) -> float:
        first, second = self._ltp_cache.get(symbol, (0.0, 0.0))
        if first > 1_000_000_000 and second >= 0:
            return float(second)
        if second > 1_000_000_000 and first >= 0:
            return float(first)
        return float(max(first, second))

    def get_lot_size(self, symbol: str) -> int:
        if cached := self._lot_cache.get(symbol):
            return cached
        return 1

    async def stream_full(self, symbols: list[str]) -> AsyncIterator[dict]:
        interval = float(os.getenv("DHAN_STREAM_INTERVAL", "1.5"))
        while True:
            now_ts = datetime.now(tz=IST).isoformat()
            emitted = False
            for symbol in symbols:
                ltp = self.get_ltp(symbol)
                if ltp <= 0:
                    continue
                emitted = True
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
            if not emitted and not self._access_token:
                return
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
        # Try cache first
        cached = self._option_chain_cache.get(underlying, exchange, expiry_index)
        if cached is not None:
            return cached

        t0 = time.monotonic()
        request_awaitable = self._client.get(
            "/api/options/chain",
            params={
                "underlying": underlying,
                "exchange": exchange,
                "expiry_index": expiry_index,
            },
        )
        response = self._run_sync(request_awaitable)
        latency = (time.monotonic() - t0) * 1000
        if inspect.iscoroutine(request_awaitable):
            request_awaitable.close()
        if response is None or response.status_code != 200:
            if _HAS_COST_TRACKING:
                get_cost_tracker().record_api_call(
                    "/api/options/chain", underlying, latency,
                    "error" if response and response.status_code != 200 else "error"
                )
            return None
        if _HAS_COST_TRACKING:
            get_cost_tracker().record_api_call("/api/options/chain", underlying, latency, "ok")
        payload = _safe_json(response, None)
        chain = _parse_option_chain(payload, underlying=underlying, exchange=exchange)
        if chain is None:
            return None

        self._option_chain_cache.set(underlying, exchange, expiry_index, chain)
        return chain

    def _run_sync(self, awaitable: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                return asyncio.run(awaitable)
            return loop.run_until_complete(awaitable)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._run_async_in_thread, awaitable)
            return future.result()

    def _run_async_in_thread(self, awaitable: Any) -> Any:
        return asyncio.run(awaitable)


@dataclass(frozen=True)
class _OptionContract:
    symbol: str
    ltp: float
    oi: int
    volume: int
    bid: float
    ask: float
    delta: float
    iv: float


@dataclass(frozen=True)
class _OptionChain:
    expiry: Any
    spot_price: float
    atm_strike: float
    calls: dict[float, _OptionContract]
    puts: dict[float, _OptionContract]


def _parse_option_chain(payload: Any, *, underlying: str, exchange: str) -> _OptionChain | None:
    if not isinstance(payload, dict):
        return None

    data = payload.get("data", payload)
    expiry = data.get("expiry", data.get("expiryDate", ""))
    if isinstance(expiry, str) and expiry:
        try:
            expiry = datetime.fromisoformat(expiry)
        except Exception:
            pass
    spot_price = _safe_float(data, ("spot", "spotPrice", "spot_price"))
    atm_strike = _safe_float(data, ("atm", "atmStrike", "atm_strike"))
    calls = _coerce_option_map(data.get("calls") or data.get("call") or data.get("ce"), underlying=underlying, exchange=exchange)
    puts = _coerce_option_map(data.get("puts") or data.get("put") or data.get("pe"), underlying=underlying, exchange=exchange)
    if not calls or not puts:
        if not calls and not puts:
            return None
    return _OptionChain(
        expiry=expiry,
        spot_price=float(spot_price),
        atm_strike=float(atm_strike),
        calls=calls,
        puts=puts,
    )


def _coerce_option_map(value: Any, *, underlying: str, exchange: str) -> dict[float, _OptionContract]:
    items: dict[float, _OptionContract] = {}
    if isinstance(value, dict):
        iterable = value.items()
    elif isinstance(value, list):
        iterable = []
        for raw in value:
            if isinstance(raw, dict):
                iterable.append((raw.get("strike"), raw))
    else:
        return items

    for strike_key, raw in iterable:
        try:
            strike = float(strike_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        contract = _OptionContract(
            symbol=str(raw.get("symbol", _build_symbol_fallback(underlying, int(strike), exchange))),
            ltp=_safe_float(raw, ("ltp", "lastPrice", "price")),
            oi=_safe_int(raw, ("oi", "openInterest", "open_interest")),
            volume=_safe_int(raw, ("volume", "tradedVolume")),
            bid=_safe_float(raw, ("bid", "bestBid", "bidPrice", "bid_price")),
            ask=_safe_float(raw, ("ask", "bestAsk", "askPrice", "ask_price")),
            delta=_safe_float(raw, ("delta",), default=0.5),
            iv=_safe_float(raw, ("iv", "impliedVolatility", "ivPercent"), default=0.0),
        )
        items[strike] = contract
    return items


def _build_symbol_fallback(underlying: str, strike: int, exchange: str) -> str:
    return f"{underlying} {exchange[:3]} {strike}"


def _safe_float(data: Any, keys: tuple[str, ...], default: float = 0.0) -> float:
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                try:
                    return float(data[key])
                except (TypeError, ValueError):
                    pass
    return default


def _safe_int(data: Any, keys: tuple[str, ...], default: int = 0) -> int:
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                try:
                    return int(float(data[key]))
                except (TypeError, ValueError):
                    pass
    return default


def _safe_json(response: Any, fallback: Any | None = None) -> Any:
    try:
        return response.json()
    except Exception:
        return fallback if fallback is not None else {}
