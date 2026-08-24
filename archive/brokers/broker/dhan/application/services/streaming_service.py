"""
Streaming Service - Real-time WebSocket streaming operations.

Maintains a single persistent WebSocket per feed type (full + depth)
that lives for the broker lifetime.  Instruments are dynamically
subscribed/unsubscribed on the existing connection via the
subscription management API — no new connections are created per call.
"""

import asyncio
from typing import Dict, List, Optional, Tuple, AsyncIterator

from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    MarketDepth,
    DepthLevel,
    FullPacket,
)
from brokers.broker.dhan.domain.constants import (
    WS_URL,
    FEED_TYPE_TICKER,
    FEED_TYPE_QUOTE,
    FEED_TYPE_FULL,
)
from brokers.broker.dhan.domain.errors import DhanFeedNotSupportedError
from brokers.broker.dhan.domain.segment_mapping import exchange_to_segment_name
from brokers.broker.types import Exchange
from brokers.broker.dhan.infrastructure.websocket_client import DhanWebSocketClient
from brokers.broker.dhan.infrastructure.depth_websocket_client import DepthWebSocketClient
from brokers.broker.logging import get_logger
from .base import BaseDhanService

logger = get_logger("dhan.services.streaming")


class StreamingService(BaseDhanService):
    """Handles real-time WebSocket streaming operations.

    A single persistent WebSocket is created on first use and reused
    for all subsequent `stream_full()` calls.  Instruments are
    dynamically added/removed on the existing connection via
    subscribe/unsubscribe — no new connections per call.
    """

    def __init__(self, *args, **kwargs):
        # Forward all positional/keyword args to BaseDhanService
        # Base __init__: (config, http_client, symbol_mapper, rate_limiter,
        #                 circuit_breaker, option_symbol_cache, ensure_initialized)
        self._config = kwargs.get("config", args[0] if len(args) > 0 else None)
        self._http_client = kwargs.get("http_client", args[1] if len(args) > 1 else None)
        self._symbol_mapper = kwargs.get("symbol_mapper", args[2] if len(args) > 2 else None)
        self._rate_limiter = kwargs.get("rate_limiter", args[3] if len(args) > 3 else None)
        self._circuit_breaker = kwargs.get("circuit_breaker", args[4] if len(args) > 4 else None)
        self._option_symbol_cache = kwargs.get("option_symbol_cache", args[5] if len(args) > 5 else {})
        self._ensure_initialized = kwargs.get("ensure_initialized", args[6] if len(args) > 6 else None)

        # Persistent WebSocket state (lazy-initialized, one per lifetime)
        self._persistent_ws: Optional[DhanWebSocketClient] = None
        self._persistent_depth_ws: Optional[DepthWebSocketClient] = None
        self._ws_lock = asyncio.Lock()
        self._depth_ws_lock = asyncio.Lock()

    def _make_ws_client(self):
        """For tests and factory injection — not used at runtime."""
        factory = getattr(self, '_ws_client_factory', None)
        if factory:
            return factory()
        return DhanWebSocketClient(
            ws_url=WS_URL,
            access_token=self._config.access_token,
            client_id=self._config.client_id,
        )

    def _make_depth_client(self, depth_level: int):
        factory = getattr(self, '_depth_client_factory', None)
        if factory:
            return factory(depth_level)
        return DepthWebSocketClient(
            depth_level=depth_level,
            access_token=self._config.access_token,
            client_id=self._config.client_id,
        )

    async def _get_persistent_ws(self, instruments: List[Instrument]) -> DhanWebSocketClient:
        """Return a single persistent WebSocket client.  Creates and connects
        on first call; reuses on subsequent calls.

        All instruments must be subscribed before the generator is consumed.
        """
        async with self._ws_lock:
            ws = self._persistent_ws
            if ws is not None and ws.is_connected:
                return ws

            # Connection lost or not yet created — build fresh
            if ws is not None:
                logger.warning("Persistent WS lost — reconnecting…")
                try:
                    await ws.disconnect()
                except Exception:
                    pass

            ws = self._make_ws_client()
            await ws.connect()
            self._persistent_ws = ws
            logger.info("Persistent WebSocket created and ready")
            return ws

    async def _get_persistent_depth_ws(self, instruments: List[Instrument]) -> DepthWebSocketClient:
        async with self._depth_ws_lock:
            ws = self._persistent_depth_ws
            if ws is not None and ws.is_connected:
                return ws

            if ws is not None:
                logger.warning("Persistent depth WS lost — reconnecting…")
                try:
                    await ws.disconnect()
                except Exception:
                    pass

            ws = self._make_depth_client(20)
            await ws.connect()
            self._persistent_depth_ws = ws
            logger.info("Persistent depth WebSocket created and ready")
            return ws

    async def disconnect_persistent(self) -> None:
        """Close all persistent WebSockets.  Called during broker shutdown."""
        if self._persistent_ws:
            try:
                await self._persistent_ws.disconnect()
            except Exception:
                pass
            self._persistent_ws = None
            logger.info("Persistent WS closed")

        if self._persistent_depth_ws:
            try:
                await self._persistent_depth_ws.disconnect()
            except Exception:
                pass
            self._persistent_depth_ws = None
            logger.info("Persistent depth WS closed")

    async def _prepare_stream(
        self, instruments: List[Instrument]
    ) -> Tuple[List[str], Dict[str, Instrument]]:
        """Shared setup for all streaming methods."""
        await self._ensure_initialized()
        return await self._resolve_instruments_parallel(instruments)

    def _exchange_segments_for(
        self,
        security_ids: List[str],
        instrument_map: Dict[str, Instrument],
    ) -> List[str]:
        """
        Build the exchange segment list matching security_ids order.

        Uses exchange_to_segment_name to convert each Instrument.exchange
        to the Dhan segment string (e.g. "NSE_EQ", "NSE_FNO", "MCX_COMM").
        Falls back to "NSE_EQ" if the instrument is not found in the map.
        """
        segments = []
        for sid in security_ids:
            inst = instrument_map.get(sid)
            if inst:
                try:
                    seg = exchange_to_segment_name(inst.exchange)
                    segments.append(seg)
                except Exception:
                    segments.append("NSE_EQ")
            else:
                segments.append("NSE_EQ")
        return segments

    def _check_no_mcx(self, instrument_map: Dict[str, Instrument], feed_type: str) -> None:
        """Raise DhanFeedNotSupportedError if any instrument is MCX."""
        for inst in instrument_map.values():
            if inst.exchange == Exchange.MCX:
                raise DhanFeedNotSupportedError(
                    message=f"{feed_type} feed not supported for MCX. Use stream_full().",
                    feed_type=feed_type,
                    exchange="MCX",
                    details={"instrument": inst.symbol},
                )

    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]:
        """Stream real-time ticker data (LTP only) via DhanWebSocketClient."""
        security_ids, instrument_map = await self._prepare_stream(instruments)
        if not security_ids:
            return
        self._check_no_mcx(instrument_map, "TICKER")
        exchange_segments = self._exchange_segments_for(security_ids, instrument_map)

        ws_client = self._make_ws_client()
        await ws_client.connect()
        try:
            await ws_client.subscribe(security_ids, feed_type=FEED_TYPE_TICKER,
                                      exchange_segments=exchange_segments)
            async for msg in ws_client.messages():
                if msg.type == "tick":
                    sid = str(msg.data.get("security_id", ""))
                    inst = instrument_map.get(sid)
                    if inst:
                        yield Tick(
                            instrument=inst,
                            price=float(msg.data.get("ltp", 0.0)),
                            volume=int(msg.data.get("volume", 0)),
                            timestamp=msg.timestamp,
                            bid=msg.data.get("bid"),
                            ask=msg.data.get("ask"),
                        )
        finally:
            await ws_client.disconnect()

    async def stream_quotes(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[Quote]:
        """Stream real-time quote data (LTP + OHLC + volume + bid/ask)."""
        security_ids, instrument_map = await self._prepare_stream(instruments)
        if not security_ids:
            return
        self._check_no_mcx(instrument_map, "QUOTE")
        exchange_segments = self._exchange_segments_for(security_ids, instrument_map)

        ws_client = self._make_ws_client()
        await ws_client.connect()
        try:
            await ws_client.subscribe(security_ids, feed_type=FEED_TYPE_QUOTE,
                                      exchange_segments=exchange_segments)
            async for msg in ws_client.messages():
                if msg.type == "quote":
                    sid = str(msg.data.get("security_id", ""))
                    inst = instrument_map.get(sid)
                    if inst:
                        yield Quote(
                            instrument=inst,
                            ltp=float(msg.data.get("ltp", 0.0)),
                            bid=float(msg.data.get("bid", 0.0) or 0.0),
                            ask=float(msg.data.get("ask", 0.0) or 0.0),
                            volume=int(msg.data.get("volume", 0)),
                            open=float(msg.data.get("open", 0.0) or 0.0),
                            high=float(msg.data.get("high", 0.0) or 0.0),
                            low=float(msg.data.get("low", 0.0) or 0.0),
                            close=float(msg.data.get("close", 0.0) or 0.0),
                            timestamp=msg.timestamp,
                        )
        finally:
            await ws_client.disconnect()

    async def stream_depth(
        self, instruments: List[Instrument], depth_level: int = 20
    ) -> AsyncIterator[MarketDepth]:
        """
        Stream market depth data.

        depth_level=5  → regular feed (5-level via FEED_TYPE_FULL on WS_URL)
        depth_level=20 → dedicated 20-level depth feed (DepthWebSocketClient)
        depth_level=200 → dedicated 200-level depth feed (single instrument)
        """
        if depth_level == 20:
            async for md in self.stream_depth_20(instruments):
                yield md
        elif depth_level == 200:
            async for md in self.stream_depth_200(instruments):
                yield md
        else:
            # depth_level=5 or any other value → fall back to 5-level regular feed
            async for md in self._stream_depth_5(instruments):
                yield md

    async def _stream_depth_5(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[MarketDepth]:
        """Stream 5-level depth via the regular market feed (FEED_TYPE_FULL=21)."""
        security_ids, instrument_map = await self._prepare_stream(instruments)
        if not security_ids:
            return
        exchange_segments = self._exchange_segments_for(security_ids, instrument_map)

        ws_client = self._make_ws_client()
        await ws_client.connect()
        try:
            await ws_client.subscribe(security_ids, feed_type=FEED_TYPE_FULL,
                                      exchange_segments=exchange_segments)
            async for msg in ws_client.messages():
                if msg.type == "full":
                    sid = str(msg.data.get("security_id", ""))
                    inst = instrument_map.get(sid)
                    if inst:
                        for side, key in (("bid", "depth_bids"), ("ask", "depth_asks")):
                            raw_levels = msg.data.get(key, [])
                            if raw_levels:
                                yield MarketDepth(
                                    symbol=inst.symbol,
                                    security_id=sid,
                                    side=side,
                                    levels=[
                                        DepthLevel(
                                            price=float(lvl.get("price", 0)),
                                            quantity=int(lvl.get("qty", 0)),
                                            orders=lvl.get("orders"),
                                        )
                                        for lvl in raw_levels
                                    ],
                                    timestamp=msg.timestamp,
                                )
        finally:
            await ws_client.disconnect()

    async def stream_depth_20(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[MarketDepth]:
        """Stream 20-level market depth via persistent depth WS."""
        security_ids, instrument_map = await self._prepare_stream(instruments)
        if not security_ids:
            return

        exchange_segments = self._exchange_segments_for(security_ids, instrument_map)

        ws = await self._get_persistent_depth_ws(instruments)

        await ws.subscribe(
            security_ids,
            feed_type=20,
            exchange_segments=exchange_segments,
        )
        try:
            async for msg in ws.messages():
                if msg.type == "depth":
                    sid = str(msg.data.get("security_id", ""))
                    inst = instrument_map.get(sid)
                    if inst:
                        yield MarketDepth(
                            symbol=inst.symbol,
                            security_id=sid,
                            side=msg.data["side"],
                            levels=[
                                DepthLevel(
                                    price=float(lvl["price"]),
                                    quantity=int(lvl["qty"]),
                                    orders=lvl.get("orders"),
                                )
                                for lvl in msg.data.get("levels", [])
                            ],
                            timestamp=msg.timestamp,
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("stream_depth_20: WS error — will reconnect on next call: %s", e)
            async with self._depth_ws_lock:
                self._persistent_depth_ws = None

    async def stream_depth_200(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[MarketDepth]:
        """
        Stream 200-level market depth via the dedicated full-depth feed.

        Only 1 instrument per connection is supported by Dhan.
        If more than one instrument is provided, only the first is used.
        Each yielded MarketDepth has symbol backfilled from the instrument map.
        """
        # 200-level: single instrument only — take first, warn if caller passed more
        if len(instruments) > 1:
            logger.warning(
                f"stream_depth_200 only supports 1 instrument per connection; "
                f"ignoring {len(instruments) - 1} extra instrument(s)"
            )
        first = instruments[:1]
        security_ids, instrument_map = await self._prepare_stream(first)
        if not security_ids:
            return

        exchange_segments = self._exchange_segments_for(security_ids, instrument_map)

        ws_client = self._make_depth_client(200)
        await ws_client.connect()
        try:
            await ws_client.subscribe(
                security_ids,
                feed_type=200,  # ignored — DepthWebSocketClient uses DEPTH_REQUEST_CODE=23
                exchange_segments=exchange_segments,
            )
            async for msg in ws_client.messages():
                if msg.type == "depth":
                    sid = str(msg.data.get("security_id", ""))
                    inst = instrument_map.get(sid)
                    if inst:
                        yield MarketDepth(
                            symbol=inst.symbol,
                            security_id=sid,
                            side=msg.data["side"],
                            levels=[
                                DepthLevel(
                                    price=float(lvl["price"]),
                                    quantity=int(lvl["qty"]),
                                    orders=lvl.get("orders"),
                                )
                                for lvl in msg.data.get("levels", [])
                            ],
                            timestamp=msg.timestamp,
                        )
        finally:
            await ws_client.disconnect()

    async def stream_full(
        self, instruments: List[Instrument]
    ) -> AsyncIterator[FullPacket]:
        """
        Stream market data as FullPacket for any exchange segment.

        Uses a single persistent WebSocket across calls.  Instruments are
        subscribed on the existing connection — no new connections are created.
        Dropped symbols (expired options) are unsubscribed to free slots.
        """
        security_ids, instrument_map = await self._prepare_stream(instruments)
        if not security_ids:
            return

        exchange_segments = self._exchange_segments_for(security_ids, instrument_map)

        feed_type = FEED_TYPE_FULL
        accepted_types = ("full", "quote", "tick")

        # Get or create persistent WS (connects only once for the broker lifetime)
        ws = await self._get_persistent_ws(instruments)

        # Subscribe new instruments on the existing connection.
        # Skip if already subscribed — avoids double-subscribe on reconnect
        # (the WS client's connect() re-sends all subscriptions).
        new_sids = [sid for sid in security_ids if sid not in ws.subscriptions]
        if new_sids:
            logger.info("Subscribing %d new instrument(s) on persistent WS", len(new_sids))
            await ws.subscribe(new_sids, feed_type=feed_type,
                               exchange_segments=exchange_segments)

        # Yield packets until WS disconnects (expired symbols, network error)
        try:
            async for msg in ws.messages():
                if msg.type in accepted_types:
                    sid = str(msg.data.get("security_id", ""))
                    inst = instrument_map.get(sid)
                    if inst:
                        d = msg.data
                        yield FullPacket(
                            symbol=inst.symbol,
                            ltp=float(d.get("ltp", 0)),
                            open=float(d.get("open", 0)),
                            high=float(d.get("high", 0)),
                            low=float(d.get("low", 0)),
                            close=float(d.get("close", 0)),
                            volume=int(d.get("volume", 0)),
                            oi=int(d.get("oi", 0)),
                            atp=float(d.get("atp", 0)),
                            total_buy_qty=int(d.get("total_buy_qty", 0)),
                            total_sell_qty=int(d.get("total_sell_qty", 0)),
                            depth_bids=tuple(d.get("depth_bids", ())),
                            depth_asks=tuple(d.get("depth_asks", ())),
                            security_id=sid,
                            exchange_segment=str(d.get("exchange_segment", "")),
                            timestamp=msg.timestamp,
                            ltq=int(d.get("ltq", 0)),
                            ltt=int(d.get("last_trade_time", 0)),
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("stream_full: WS error — will reconnect on next call: %s", e)
            # Clear the persistent ref so next call gets a fresh connection
            async with self._ws_lock:
                self._persistent_ws = None
