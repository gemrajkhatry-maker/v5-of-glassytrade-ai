"""Dhan market data adapter — implements MarketDataPort using the brokers/ library.

Provides historical candle data, quote snapshots, and live streaming for
NSE/NFO/MCX instruments via DhanBroker from the brokers/ package.

NSE does not provide taker_buy_volume, so delta is approximated from candle body.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

# Add project root to sys.path so `from brokers.broker...` resolves correctly.
# Discovers the root by walking up until we find the brokers/ directory.
_here = pathlib.Path(__file__).resolve()
for _ancestor in _here.parents:
    if (_ancestor / "brokers").is_dir():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
from app.domain.ports.market_data import MarketDataPort

logger = logging.getLogger(__name__)

from app.shared.timezones import IST


# ---------------------------------------------------------------------------


def _delta_proxy(o: float, h: float, l: float, c: float, v: float) -> float:
    """Approximate delta from candle body when taker_buy_volume unavailable."""
    spread = h - l
    if spread <= 0 or v <= 0:
        return 0.0
    body_ratio = (c - o) / spread  # -1 to +1
    return body_ratio * v


def _exchange_enum(exchange_str: str | None):
    """Convert exchange string to brokers Exchange enum."""
    from brokers.broker.types import Exchange

    mapping = {
        "NSE": Exchange.NSE,
        "NFO": Exchange.NFO,
        "MCX": Exchange.MCX,
        "BSE": Exchange.NSE,  # fallback
    }
    result = mapping.get((exchange_str or "NSE").upper())
    if result is None:
        logger.warning("Unknown exchange '%s', defaulting to NSE", exchange_str)
        result = Exchange.NSE
    return result


class DhanMarketDataAdapter(MarketDataPort):
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

    _MCX_UNDERLYINGS = frozenset(
        {
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "NATURALGAS",
            "GOLDM",
            "SILVERM",
            "CRUDEOILM",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
            "LEAD",
            "NICKEL",
            "COTTONCANDY",
        }
    )

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
        is_option = ("CALL" in sym_upper or "PUT" in sym_upper
                     or sym_upper.endswith("CE") or sym_upper.endswith("PE"))
        if is_option:
            # Detect exchange from the underlying name embedded in the symbol
            is_mcx = any(sym_upper.startswith(u) for u in self._MCX_UNDERLYINGS)
            exchange = _exchange_enum("MCX" if is_mcx else "NFO")
            option_type = OptionType.CALL if ("CALL" in sym_upper or sym_upper.endswith("CE")) else OptionType.PUT
            return Instrument(symbol=symbol, exchange=exchange, option_type=option_type)
        else:
            exchange = _exchange_enum(self._exchange_str)
            return Instrument(symbol=symbol, exchange=exchange)

    def get_option_chain(
        self, underlying: str, exchange: str = "NFO", expiry_index: int = 0
    ):
        """Fetch option chain, converting string exchange to broker enum.

        Returns None if chain is unavailable (e.g., MCX commodity without options).
        """
        try:
            self.ensure_initialized_sync()
            broker = self.get_broker()
            ex = _exchange_enum(exchange)
            return broker.get_option_chain(
                underlying=underlying,
                exchange=ex,
                expiry_index=expiry_index,
            )
        except Exception as e:
            logger.debug("get_option_chain(%s, %s) failed: %s", underlying, exchange, e)
            return None

    async def scan_candidates(self, limit: int = 6) -> list[str]:
        return self._symbols[:limit]

    async def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 500
    ) -> list[OHLC]:
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
                delta = _delta_proxy(o, h, l, c, v)
                vwap = (h + l + c) / 3  # industry-standard typical price

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
            return result
        except Exception:
            logger.exception("Failed to fetch history for %s", symbol)
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
            logger.debug("Order book fetch failed for %s", symbol, exc_info=True)
            return None

    def get_ltp(self, symbol: str) -> float:
        """Get last traded price (synchronous)."""
        try:
            self.ensure_initialized_sync()
            broker = self.get_broker()
            instrument = self._make_instrument(symbol)
            return float(broker.get_ltp(instrument))
        except Exception:
            logger.debug("LTP fetch failed for %s", symbol, exc_info=True)
            return 0.0

    async def stream_full(self, symbols: list[str]) -> AsyncIterator[dict]:
        """Stream live FULL packets via DhanBroker.stream_full().

        Converts FullPacket → dict for backward compatibility with gameloop.
        """
        await self._ensure_initialized()
        broker = self.get_broker()

        instruments = [self._make_instrument(sym) for sym in symbols]

        pkt_count = 0
        async for pkt in broker.stream_full(instruments):
            pkt_count += 1
            if pkt_count <= 3 or pkt_count % 100 == 0:
                logger.debug(
                    "stream_full pkt #%d: ltp=%s", pkt_count, getattr(pkt, "ltp", "?")
                )
            yield asdict(pkt)

    async def stream_poll(
        self, symbols: list[str], poll_interval: float = 3.0
    ) -> AsyncIterator[dict]:
        """REST LTP polling fallback when Dhan WS returns no data for MCX OPTFUT.

        Polls broker.get_ltp() for each symbol every poll_interval seconds and
        yields tick dicts in the same schema as stream_full(). Volume fields are
        zero because REST LTP doesn't carry volume; the candle builder handles this.
        """
        await self._ensure_initialized()
        broker = self.get_broker()
        loop = asyncio.get_event_loop()

        logger.info,(
            "stream_poll: REST polling %d symbol(s) every %.1fs (MCX OPTFUT fallback)",
            len(symbols),
            poll_interval,
        )

        while True:
            poll_start = loop.time()
            for sym in symbols:
                try:
                    instrument = self._make_instrument(sym)
                    ltp = await loop.run_in_executor(
                        None, lambda i=instrument: float(broker.get_ltp(i))
                    )
                    if ltp > 0:
                        yield {
                            "symbol": sym,
                            "ltp": ltp,
                            "timestamp": datetime.now(IST).isoformat(),
                            # WS-absent fields — candle builder treats vol=0 as "no new volume"
                            "volume": 0,
                            "ltq": 0,
                            "oi": 0,
                            "total_buy_qty": 0,
                            "total_sell_qty": 0,
                            "depth_bids": [],
                            "depth_asks": [],
                        }
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug(
                        "stream_poll: LTP fetch failed for %s", sym, exc_info=True
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
        async for depth in broker.stream_depth(instruments, depth_level=20):
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
