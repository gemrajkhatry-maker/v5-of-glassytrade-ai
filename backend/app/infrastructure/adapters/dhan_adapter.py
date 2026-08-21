"""Dhan market data adapter — implements IMarketData using the brokers/ library.

Provides historical candle data, quote snapshots, and live streaming for
NSE/NFO/MCX instruments via DhanBroker from the brokers/ package.

NSE does not provide taker_buy_volume, so delta is approximated from candle body.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator

from app.infrastructure.adapters._dhan_common import _exchange_enum, classify_symbol
from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from quant.contracts.ports.market_data import IMarketData
from quant.contracts.market_data_utils import compute_vwap_approx, estimate_tick_delta
from quant.contracts.exchange_config import ExchangeConfig

logger = logging.getLogger(__name__)

from quant.contracts.timezones import IST


def _delta_proxy(
    open_price: float, high: float, low: float, close: float, volume: float
) -> float:
    """Backward-compatible delta proxy used by legacy tests."""
    return estimate_tick_delta(open_price, high, low, close, volume)


# ---------------------------------------------------------------------------


class DhanMarketDataAdapter(IMarketData):
    """Dhan market data adapter using the brokers/ DhanBroker library.

    Initialization is guarded by a threading lock so that exactly one
    caller (sync or async) performs broker.initialize() and all others
    wait on the result.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        exchange: str | None = None,
        client_id: str | None = None,
        access_token: str | None = None,
    ) -> None:
        self._symbols = symbols or ["NIFTY", "BANKNIFTY"]
        self._exchange_str = exchange  # e.g. "MCX", "NSE", "NFO"
        self._client_id = client_id
        self._access_token = access_token
        self._broker = None
        # Single init guard — thread-safe for both sync and async callers
        self._init_lock = threading.Lock()
        self._initialized = False
        # Short-TTL cache for option chains (reduces duplicate API load on rescans / expiry probes)
        self._chain_cache: dict[tuple[str, str, int], tuple[object, float]] = {}
        self._chain_cache_lock = threading.Lock()
        self._chain_cache_ttl = float(os.environ.get("OPTION_CHAIN_CACHE_TTL_SEC", "8.0"))
        # Short-TTL cache for historical candles (30s) to prevent API rate limits
        self._history_cache: dict[tuple[str, str], tuple[list[OHLC], float]] = {}
        self._history_cache_lock = threading.Lock()
        self._history_cache_ttl = 30.0
        # Optional: serialize broker option-chain calls (set when broker is not thread-safe).
        self._serialize_option_chain_fetch = os.environ.get(
            "DHAN_SERIALIZE_OPTION_CHAIN", ""
        ).lower() in ("1", "true", "yes")
        self._option_chain_broker_lock = threading.Lock()

    def get_broker(self):
        """Return DhanBroker instance (lazy-created, cached)."""
        if self._broker is None:
            from brokers.broker.dhan.application.broker import DhanBroker

            self._broker = DhanBroker.create(
                client_id=self._client_id,
                access_token=self._access_token,
            )
            logger.info("DhanBroker created")
        return self._broker

    def ensure_initialized_sync(self, timeout: float = 120) -> None:
        """Synchronous init — safe to call from any thread.

        Creates a temporary event loop to drive the async initialize().
        """
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            broker = self.get_broker()
            if not broker.is_initialized:
                logger.info(
                    "Initializing DhanBroker (sync path, timeout=%ss)...", timeout
                )
                try:
                    try:
                        active_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        active_loop = None

                    if active_loop is not None and active_loop.is_running():
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            pool.submit(
                                lambda: asyncio.run(
                                    asyncio.wait_for(broker.initialize(), timeout=timeout)
                                )
                            ).result()
                    else:
                        loop = asyncio.new_event_loop()
                        try:
                            loop.run_until_complete(
                                asyncio.wait_for(broker.initialize(), timeout=timeout)
                            )
                        finally:
                            loop.close()
                except Exception as e:
                    logger.error("DhanBroker initialization failed: %s", e)
                    raise  # Propagate so caller knows init failed
            self._initialized = True
            logger.info("DhanBroker initialized (instrument cache ready)")

    async def _ensure_initialized(self):
        """Async init — safe to call from event loop."""
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            broker = self.get_broker()
            if not broker.is_initialized:
                logger.info("Initializing DhanBroker (async path)...")
                try:
                    await broker.initialize()
                except Exception as e:
                    logger.error("DhanBroker initialization failed (async): %s", e)
                    raise  # Propagate so caller knows init failed
            self._initialized = True
            logger.info("DhanBroker initialized (instrument cache ready)")

    _MCX_UNDERLYINGS = ExchangeConfig.for_exchange("MCX").underlyings


    def _make_instrument(self, symbol: str):
        """Build Instrument for the given display symbol.

        Auto-detects option symbols (CALL/PUT or CE/PE) and routes to
        the correct exchange: NFO for NSE underlyings, MCX for commodity underlyings.
        Sets option_type so Instrument.is_option() returns True for options —
        this is used downstream by streaming_service to select the correct
        WS exchange segment (MCX_FNO vs MCX_COMM).
        """
        from brokers.broker.entities import Instrument, OptionType

        sym_upper = symbol.upper()
        is_option, is_call, is_put, is_mcx = classify_symbol(symbol)
        if is_option:
            exchange = _exchange_enum("MCX" if is_mcx else "NFO")
            option_type = OptionType.CALL if is_call else OptionType.PUT
            return Instrument(symbol=symbol, exchange=exchange, option_type=option_type)
        elif sym_upper.endswith(" FUT"):
            # Futures roots (e.g. "NIFTY AUG FUT", "CRUDEOIL AUG FUT") — route to
            # the same derivative exchanges as options so Dhan resolves the security
            # ID in NSE_FNO / MCX_COMM instead of the equity segment.
            is_mcx = ExchangeConfig.for_exchange("MCX").is_underlying(sym_upper)
            exchange = _exchange_enum("MCX" if is_mcx else "NFO")
            return Instrument(symbol=symbol, exchange=exchange)
        else:
            exchange = _exchange_enum(self._exchange_str)
            return Instrument(symbol=symbol, exchange=exchange)

    def get_option_chain(
        self, underlying: str, exchange: str = "NFO", expiry_index: int = 0
    ):
        """Fetch option chain, converting string exchange to broker enum.

        Returns None if chain is unavailable (e.g., MCX commodity without options).
        Identical requests within ``OPTION_CHAIN_CACHE_TTL_SEC`` (default 8s) reuse
        the last chain to avoid hammering the broker on startup + rescan.
        """
        ex_key = (underlying.upper(), (exchange or "NFO").upper(), int(expiry_index))
        now = time.monotonic()
        if self._chain_cache_ttl > 0:
            with self._chain_cache_lock:
                hit = self._chain_cache.get(ex_key)
                if hit is not None:
                    chain_obj, ts = hit
                    if now - ts <= self._chain_cache_ttl:
                        return chain_obj
        try:
            self.ensure_initialized_sync()
            broker = self.get_broker()
            ex = _exchange_enum(exchange)
            if self._serialize_option_chain_fetch:
                with self._option_chain_broker_lock:
                    chain = broker.get_option_chain(
                        underlying=underlying,
                        exchange=ex,
                        expiry_index=expiry_index,
                    )
            else:
                chain = broker.get_option_chain(
                    underlying=underlying,
                    exchange=ex,
                    expiry_index=expiry_index,
                )
        except Exception as e:
            logger.debug("get_option_chain(%s, %s) failed: %s", underlying, exchange, e)
            return None
        if chain is not None and self._chain_cache_ttl > 0:
            with self._chain_cache_lock:
                self._chain_cache[ex_key] = (chain, time.monotonic())
                if len(self._chain_cache) > 64:
                    # Drop stale entries (keep memory bounded on long runs)
                    cutoff = time.monotonic() - self._chain_cache_ttl
                    for k, (_, t) in list(self._chain_cache.items()):
                        if t < cutoff:
                            self._chain_cache.pop(k, None)
        return chain

    async def scan_candidates(self, limit: int = 6) -> list[str]:
        return self._symbols[:limit]

    async def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 500
    ) -> list[OHLC]:
        cache_key = (symbol, interval)
        with self._history_cache_lock:
            cached_entry = self._history_cache.get(cache_key)
            if cached_entry:
                cached_data, cached_ts = cached_entry
                if (time.time() - cached_ts) < self._history_cache_ttl:
                    return cached_data[-limit:]

        try:
            await self._ensure_initialized()
            broker = self.get_broker()

            instrument = self._make_instrument(symbol)

            is_intraday = interval in (
                "1m",
                "5m",
                "15m",
                "25m",
                "1h",
                "60",
                "1",
                "5",
                "15",
                "25",
            )
            # FIX: Use 90 days for intraday (Dhan allows 90 days in one go)
            days_back = 90 if is_intraday else 365

            end = datetime.now(IST)
            start = end - timedelta(days=days_back)

            # Map common interval names to Dhan format
            interval_map = {
                "1m": "1",
                "5m": "5",
                "15m": "15",
                "25m": "25",
                "1h": "60",
                "60": "60",
                "1d": "1d",
            }
            dhan_interval = interval_map.get(interval, interval)

            logger.info(
                "fetch_history: symbol=%s exchange=%s interval=%s from=%s to=%s",
                instrument.symbol,
                instrument.exchange,
                dhan_interval,
                start,
                end,
            )
            df = broker.get_historical(
                instrument=instrument,
                from_date=start,
                to_date=end,
                interval=dhan_interval,
            )

            if df is None or df.empty:
                logger.warning("No historical data for %s", symbol)
                with self._history_cache_lock:
                    if cache_key in self._history_cache:
                        return self._history_cache[cache_key][0][-limit:]
                return []

            result: list[OHLC] = []
            for idx, row in df.tail(limit).iterrows():
                # Index is datetime; also try column names for robustness
                if isinstance(idx, datetime):
                    ts = idx
                else:
                    ts = row.get("timestamp") or row.get("date") or idx

                if hasattr(ts, "isoformat"):
                    # Convert to IST if needed
                    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                        ts = ts.replace(tzinfo=IST)
                    time_str = ts.astimezone(IST).isoformat()
                elif isinstance(ts, (int, float)):
                    from datetime import datetime as _dt

                    time_str = _dt.fromtimestamp(float(ts), tz=IST).isoformat()
                else:
                    time_str = str(ts)

                o = float(row["open"])
                h = float(row["high"])
                l = float(row["low"])
                c = float(row["close"])
                v = float(row.get("volume", 0))
                delta = estimate_tick_delta(o, h, l, c, v)
                vwap = compute_vwap_approx(h, l, c)

                result.append(
                    OHLC(
                        time=time_str,
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=v,
                        vwap=vwap,
                        taker_buy_volume=0.0,
                        delta=delta,
                    )
                )

            logger.info("Fetched %d candles for %s (%s)", len(result), symbol, interval)
            with self._history_cache_lock:
                self._history_cache[cache_key] = (result, time.time())
            return result
        except Exception:
            logger.warning("Failed to fetch history for %s (interval=%s, limit=%d)", symbol, interval, limit, exc_info=True)
            with self._history_cache_lock:
                if cache_key in self._history_cache:
                    return self._history_cache[cache_key][0][-limit:]
            return []

    async def fetch_order_book(self, symbol: str) -> OrderBook | None:
        try:
            await self._ensure_initialized()
            broker = self.get_broker()

            instrument = self._make_instrument(symbol)

            quote = broker.get_quote(instrument)
            bids = []
            asks = []
            if quote.bid_depth:
                for lvl in quote.bid_depth:
                    if lvl.price > 0:
                        bids.append(
                            OrderBookLevel(
                                price=float(lvl.price), quantity=float(lvl.quantity)
                            )
                        )
            if quote.ask_depth:
                for lvl in quote.ask_depth:
                    if lvl.price > 0:
                        asks.append(
                            OrderBookLevel(
                                price=float(lvl.price), quantity=float(lvl.quantity)
                            )
                        )
            if not bids and not asks:
                return None
            return OrderBook(bids=tuple(bids), asks=tuple(asks))
        except Exception:
            logger.warning("Order book fetch failed for %s", symbol, exc_info=True)
            return None

    def get_ltp(self, symbol: str) -> float:
        """Get last traded price (synchronous)."""
        try:
            self.ensure_initialized_sync()
            broker = self.get_broker()
            instrument = self._make_instrument(symbol)
            return float(broker.get_ltp(instrument))
        except Exception:
            logger.warning("LTP fetch failed for %s", symbol, exc_info=True)
            return 0.0
    
    def get_nearest_futures(self, underlying: str, exchange: str | None = None) -> str | None:
        """Resolve the active front-month futures contract symbol for an underlying."""
        try:
            self.ensure_initialized_sync()
            broker = self.get_broker()
            mapper = getattr(broker, "_symbol_mapper", None)
            if mapper is None:
                from brokers.broker.dhan.infrastructure.symbol_mapper import DhanSymbolMapper
                mapper = DhanSymbolMapper()
            from brokers.broker.dhan.domain import ExchangeSegment
            is_mcx = (exchange or self._exchange_str or "NSE").upper() == "MCX" or ExchangeConfig.for_exchange("MCX").is_underlying(underlying.upper())
            seg = ExchangeSegment.MCX if is_mcx else ExchangeSegment.NSE_FNO
            inst = mapper.get_nearest_futures_contract_sync(underlying, exchange=seg) if hasattr(mapper, "get_nearest_futures_contract_sync") else None
            if inst is None:
                # Direct lookup in cached instruments dict
                inst = mapper._by_trading_symbol.get(f"{underlying.upper()} FUT") or None
                if not inst:
                    today = date.today()
                    candidates = [
                        i for i in mapper._by_security_id.values()
                        if (i.symbol == underlying.upper() or i.trading_symbol.startswith(f"{underlying.upper()}-") or i.trading_symbol.startswith(f"{underlying.upper()} "))
                        and (i.instrument_type.value in ("FUTIDX", "FUTSTK", "FUTCOM", "FUTURES") if hasattr(i.instrument_type, "value") else True)
                        and (i.expiry_date and i.expiry_date >= today)
                    ]
                    if candidates:
                        candidates.sort(key=lambda x: x.expiry_date or date.max)
                        inst = candidates[0]
            if inst is None:
                return None
            return inst.trading_symbol or inst.symbol
        except Exception:
            logger.warning("get_nearest_futures failed for %s", underlying, exc_info=True)
            return None

    def get_lot_size(self, symbol: str) -> int:
        """Get the lot size for a symbol (exchange-authoritative).

        Routes through the broker's exchange config, which resolves an actual
        contract of the underlying.
        """
        self.ensure_initialized_sync()
        broker = self.get_broker()
        return broker.get_exchange_config().get_lot_size(symbol)

    async def stream_full(self, symbols: list[str]) -> AsyncIterator[dict]:
        """Stream live FULL packets via DhanBroker.stream_full().

        Converts FullPacket → dict for backward compatibility with gameloop.
        Falls back to REST quote polling if WebSocket is unavailable or rate-limited.
        """
        await self._ensure_initialized()
        broker = self.get_broker()

        instruments = [self._make_instrument(sym) for sym in symbols]

        try:
            pkt_count = 0
            async for pkt in broker.stream_full(instruments):
                pkt_count += 1
                if pkt_count <= 3 or pkt_count % 100 == 0:
                    logger.debug(
                        "stream_full pkt #%d: ltp=%s", pkt_count, getattr(pkt, "ltp", "?")
                    )
                yield asdict(pkt)
        except Exception as e:
            logger.warning("stream_full WebSocket ended (%s) — falling back to REST quote polling", e)
            async for pkt in self.stream_poll(symbols, poll_interval=1.0):
                yield pkt

    async def stream_poll(
        self, symbols: list[str], poll_interval: float = 1.0
    ) -> AsyncIterator[dict]:
        """REST quote/LTP polling fallback when Dhan WS is rate-limited or unavailable.

        Polls broker.get_quote() for each symbol every poll_interval seconds and
        yields tick dicts carrying real LTP, volume, and 5-level depth.
        """
        await self._ensure_initialized()
        broker = self.get_broker()
        loop = asyncio.get_event_loop()

        logger.info(
            "stream_poll: REST quote polling %d symbol(s) every %.1fs (live tick fallback)",
            len(symbols),
            poll_interval,
        )

        while True:
            poll_start = loop.time()
            for sym in symbols:
                try:
                    instrument = self._make_instrument(sym)
                    quote = await loop.run_in_executor(
                        None, lambda i=instrument: broker.get_quote(i)
                    )
                    ltp = float(getattr(quote, "ltp", 0.0) or 0.0)
                    if ltp <= 0:
                        ltp = await loop.run_in_executor(
                            None, lambda i=instrument: float(broker.get_ltp(i))
                        )
                    if ltp > 0:
                        bids = [
                            {"price": float(lvl.price), "qty": float(lvl.quantity)}
                            for lvl in getattr(quote, "bid_depth", []) or []
                            if getattr(lvl, "price", 0) > 0
                        ]
                        asks = [
                            {"price": float(lvl.price), "qty": float(lvl.quantity)}
                            for lvl in getattr(quote, "ask_depth", []) or []
                            if getattr(lvl, "price", 0) > 0
                        ]
                        yield {
                            "symbol": sym,
                            "ltp": ltp,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "volume": float(getattr(quote, "volume", 0.0) or 0.0),
                            "ltq": float(getattr(quote, "ltq", 0.0) or 0.0),
                            "oi": float(getattr(quote, "oi", 0.0) or 0.0),
                            "total_buy_qty": sum(b["qty"] for b in bids),
                            "total_sell_qty": sum(a["qty"] for a in asks),
                            "depth_bids": bids,
                            "depth_asks": asks,
                        }
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug(
                        "stream_poll: Quote fetch failed for %s", sym, exc_info=True
                    )

            # Sleep the remainder of poll_interval (accounting for fetch time)
            elapsed = loop.time() - poll_start
            sleep_for = max(0.0, poll_interval - elapsed)
            await asyncio.sleep(sleep_for)

    async def stream_depth_20(self, symbols: list[str]):
        """Stream 20-level market depth via DhanBroker.stream_depth().

        Yields MarketDepth objects with .side ("bid"/"ask") and .levels list.
        """
        await self._ensure_initialized()
        broker = self.get_broker()
        instruments = [self._make_instrument(sym) for sym in symbols]
        
        # MCX does not support 20-level depth WebSocket (MCX depth is 5-level in stream_full)
        from brokers.broker.entities import Exchange
        non_mcx = [inst for inst in instruments if getattr(inst, "exchange", None) != Exchange.MCX]
        if not non_mcx:
            return
        async for depth in broker.stream_depth(non_mcx, depth_level=20):
            yield depth

    def close_sync(self) -> None:
        """Close the underlying DhanBroker and disconnect its WebSocket."""
        if self._broker is not None:
            try:
                logger.info("Closing DhanBroker (WebSocket disconnect)...")
                self._broker.close_sync()
            except Exception:
                logger.debug("DhanBroker close failed (shutdown in progress)", exc_info=True)
            else:
                logger.info("DhanBroker closed")
