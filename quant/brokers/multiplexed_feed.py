# BROKER CONTRACT:
# The _normalize_dhan_packet() method is the ONLY place where Dhan-specific
# WebSocket field names appear. _convert() and all downstream quant logic
# reads canonical field names only. To add a new broker:
#   1. Implement a _normalize_{broker}_packet() method
#   2. Route packets to it based on feed source tag
# Never add broker field names to _convert() or downstream.

"""MultiplexedMarketFeed — one WebSocket connection, many symbols.

Dhan supports up to 1000 instruments on a single WebSocket subscription.
The old per-symbol ``LiveGateway`` opened one producer thread (and one
asyncio event loop) per symbol; the threads raced on the broker's shared
persistent WebSocket, tripping ``asyncio.Lock ... is bound to a different
event loop`` errors, and — when the WS *was* shared — N concurrent
``messages()`` consumers stole packets from the single message queue, so a
tick for symbol A consumed by gateway B's iterator was silently dropped.

``MultiplexedMarketFeed`` fixes both problems:

* exactly ONE producer thread and ONE asyncio event loop for the whole
  lifetime of the feed;
* ONE ``stream_full(all_symbols)`` call — all instruments are subscribed on
  the single persistent WebSocket in a single subscription message;
* incoming packets are demultiplexed by ``pkt["symbol"]`` into per-symbol
  ``queue.Queue`` instances that the per-symbol gateways read from.

Symbol set changes (rescan / switch) are handled by a resync event that
wakes the producer loop cross-thread (``loop.call_soon_threadsafe``). The
producer races each ``stream.__anext__()`` against the resync event: when
the set changes it abandons the current stream and re-calls
``stream_full`` with the new symbol list on the *same* loop, so the Dhan
streaming service subscribes only the new instruments on the existing
connection (``new_sids`` diff) — never a new connection.

Pure quant: imports ``quant.*`` + stdlib only.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time

from quant.brokers.gateway import Tick
from quant.contracts.timezones import IST as _IST

logger = logging.getLogger(__name__)

_IST_OFFSET_SECONDS = float(_IST.utcoffset(None).total_seconds())
# Bound per-symbol queues so a stalled consumer cannot retain hours of ticks.
_QUEUE_MAXSIZE = 4096
# Depth cache older than this is treated as dead; fall back to in-line book.
_DEPTH_CACHE_TTL_SEC = 2.0


class MultiplexedMarketFeed:
    """Single-connection, multi-symbol market feed with per-symbol queues."""

    def __init__(self, market_data) -> None:
        self._md = market_data
        self._queues: dict[str, queue.Queue] = {}
        self._readers: dict[str, set[queue.Queue]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._resync = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resync_async: asyncio.Event | None = None
        # Per-symbol cumulative-volume baselines. Dhan WS packets carry
        # CUMULATIVE vol / total_buy_qty / total_sell_qty since session open;
        # the legacy candle builder converted them to per-tick deltas with a
        # session-reset guard — the aggregator sums tick volumes, so feeding
        # it raw cumulative values would explode bar volume. ``(vol, buy, sell)``
        # per symbol.
        #
        # Per-symbol last-trade-price baselines for buy/sell attribution: Dhan
        # does NOT provide a traded buy/sell split on the WS feed (its
        # total_buy_qty/total_sell_qty are order-book bid/ask totals that
        # oscillate with every book change). Attributing each tick's traded
        # volume by price direction — up-tick = buyer-initiated, down-tick =
        # seller-initiated, flat = split — yields a bar delta that tracks the
        # exchange's real traded delta instead of order-book noise.
        #
        # Lock discipline: the producer thread is the SOLE writer of both
        # dicts (``_route``/``_convert`` run single-threaded on the producer).
        # ``unsubscribe``/``close`` pop/clear entries under ``self._lock``;
        # dict reads and writes are GIL-atomic, so a pop racing a write can
        # only drop a baseline (benign — the next packet re-baselines). Do not
        # "fix" one side to take the lock without taking it on the other.
        self._prev_cum: dict[str, tuple[float, float, float]] = {}
        self._prev_price: dict[str, float] = {}
        self._prev_ts: dict[str, float] = {}
        self._depth_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Cumulative -> per-tick delta conversion (legacy candle-builder logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _cum_to_delta(
        prev: tuple[float, float, float] | None,
        vol: float, buy: float, sell: float,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return ``(new_baseline, (dvol, dbuy, dsell))`` for a packet.

        Only ``vol`` is a true cumulative (Dhan's ``Vol`` — cumulative traded
        quantity since session open). Dhan's ``total_buy_qty``/``total_sell_qty``
        are the CURRENT order-book bid/ask totals: they oscillate with every
        book change and are NOT cumulative traded splits (their sum is far
        below ``Vol``). Guarding the session-reset on buy/sell therefore trips
        on nearly every packet, re-baselining ``vol`` and capping the next real
        delta at 10k — the bar lost ~85% of its traded volume.

        Rules:
        * A packet with NO volume fields at all (a Dhan TICKER LTP-only packet
          routed through ``stream_full``) must not touch the baseline — pass
          through with zero delta.
        * First packet for a symbol establishes the baseline (delta 0).
        * Only ``vol`` going *backwards* means a session reset — re-baseline,
          drop the spike.
        * Deltas are never capped — AMT profile/CVD/absorption require the
          full exchange-traded volume (playbook Σ V). Silent vol_cap deleted.

        The returned ``dbuy``/``dsell`` are the raw order-book-total diffs
        (legacy callers only); ``MultiplexedMarketFeed._convert`` IGNORES them
        and attributes buy/sell by tick direction via ``_attr_delta`` — the
        book-total diffs oscillate and would fabricate a per-bar delta.
        """
        if vol == 0 and buy == 0 and sell == 0:
            # TICKER packet — LTP only, no volume data. Do NOT re-baseline.
            return prev, (0.0, 0.0, 0.0)
        if prev is None:
            return (vol, buy, sell), (0.0, 0.0, 0.0)
        pvol, pbuy, psell = prev
        if vol < pvol:
            return (vol, buy, sell), (0.0, 0.0, 0.0)
        dvol = max(0.0, vol - pvol)
        dbuy = max(0.0, buy - pbuy)
        dsell = max(0.0, sell - psell)
        return (vol, buy, sell), (dvol, dbuy, dsell)

    @staticmethod
    def _attr_delta(prev_price: float | None, price: float, dvol: float) -> tuple[float, float]:
        """Split a tick's traded volume into buy/sell by price direction.

        Dhan WS carries no aggressor flag and its total_buy_qty/total_sell_qty
        are order-book totals, not traded splits — using their diffs produces a
        bar delta that oscillates with the book (e.g. +82 vs the exchange's
        real +10). Direction is the standard proxy: an up-tick is
        buyer-initiated, a down-tick seller-initiated, a flat tick (and the
        very first tick, which has no direction) splits evenly.

        ``buy + sell == dvol`` always, so bar volume stays consistent with the
        buy/sell split the footprint/aggression pipeline expects.
        """
        if dvol <= 0:
            return 0.0, 0.0
        if prev_price is None or price == prev_price:
            half = dvol / 2.0
            return half, half
        if price > prev_price:
            return dvol, 0.0
        return 0.0, dvol

    # ------------------------------------------------------------------
    # Subscription API (symbol-level)
    # ------------------------------------------------------------------

    def set_symbols(self, symbols: list[str]) -> None:
        """Register queues for every symbol and (re)start the producer with
        the full set — a single ``stream_full`` call multiplexes all of them.

        Resyncs only when the set actually changed (idempotent re-registration
        does not restart the live stream)."""
        with self._lock:
            before = set(self._queues.keys())
            for sym in symbols:
                self._queues.setdefault(sym, queue.Queue(maxsize=_QUEUE_MAXSIZE))
            changed = set(symbols) != before
        self._kick(changed=changed)

    def subscribe(self, symbol: str) -> None:
        """Register one symbol (idempotent). Resyncs only if it is new."""
        with self._lock:
            fresh = symbol not in self._queues
            self._queues.setdefault(symbol, queue.Queue(maxsize=_QUEUE_MAXSIZE))
        self._kick(changed=fresh)

    def unsubscribe(self, symbol: str) -> None:
        """Drop a symbol's queue and unblock any reader blocked on it."""
        with self._lock:
            q = self._queues.pop(symbol, None)
            self._prev_cum.pop(symbol, None)
            self._prev_price.pop(symbol, None)
            self._prev_ts.pop(symbol, None)
            self._depth_cache.pop(symbol, None)
        if q is not None:
            q.put(None)
        self._resync.set()
        self._wake_loop()

    def next_tick(self, symbol: str) -> Tick | None:
        """Blocking read for one symbol (None when unsubscribed/closed)."""
        q = self._queues.get(symbol)
        if q is None:
            return None
        return q.get()

    def try_next_tick(self, symbol: str) -> Tick | None:
        """Non-blocking read for one symbol (None when queue is empty)."""
        q = self._queues.get(symbol)
        if q is None:
            return None
        try:
            return q.get_nowait()
        except queue.Empty:
            return None

    def add_reader(self, symbol: str) -> queue.Queue:
        """Return a non-consuming copy stream for a second engine."""
        reader = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._readers.setdefault(symbol, set()).add(reader)
        return reader

    def remove_reader(self, symbol: str, reader: queue.Queue) -> None:
        with self._lock:
            readers = self._readers.get(symbol)
            if readers is not None:
                readers.discard(reader)
                if not readers:
                    self._readers.pop(symbol, None)
        reader.put(None)

    def close(self) -> None:
        """Stop the producer thread and unblock every reader."""
        self._stop.set()
        self._wake_loop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with self._lock:
            self._prev_cum.clear()
            self._prev_price.clear()
            queues = tuple(self._queues.values())
            readers = tuple(
                reader
                for symbol_readers in self._readers.values()
                for reader in symbol_readers
            )
            self._readers.clear()
        for q in queues:
            q.put(None)
        for reader in readers:
            reader.put(None)

    # ------------------------------------------------------------------
    # Producer
    # ------------------------------------------------------------------

    def _kick(self, changed: bool = True) -> None:
        """Start the producer if not running, else signal a resync when the
        symbol set changed (a fresh symbol needs subscribing on the wire)."""
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
        if running:
            if changed:
                self._resync.set()
                self._wake_loop()
        else:
            self._thread = threading.Thread(
                target=self._producer, daemon=True, name="quant-mux-feed"
            )
            self._thread.start()

    def _wake_loop(self) -> None:
        """Wake the producer's event loop from another thread."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._set_async_resync)

    def _set_async_resync(self) -> None:
        if self._resync_async is not None:
            self._resync_async.set()

    def _snapshot_symbols(self) -> list[str]:
        with self._lock:
            return list(self._queues.keys())

    def _producer(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._consume_loop())
        except Exception:
            logger.exception("MultiplexedMarketFeed producer crashed")
        finally:
            self._loop = None
            loop.close()

    async def _consume_loop(self) -> None:
        consecutive_errors = 0
        while not self._stop.is_set():
            symbols = self._snapshot_symbols()
            if not symbols:
                await asyncio.sleep(0.5)
                continue
            
            pending = self._resync.is_set()
            self._resync_async = asyncio.Event()
            if pending:
                self._resync_async.set()
            self._resync.clear()
            
            stream_full = None
            stream_depth = None
            try:
                stream_full = self._md.stream_full(symbols)
                if hasattr(self._md, "stream_depth_20"):
                    stream_depth = self._md.stream_depth_20(symbols)
                anext_full = None
                anext_depth = None
                while True:
                    if self._stop.is_set() or self._resync.is_set():
                        break
                        
                    tasks = set()
                    resync_task = asyncio.ensure_future(self._resync_async.wait())
                    tasks.add(resync_task)
                    
                    if anext_full is None:
                        anext_full = asyncio.ensure_future(stream_full.__anext__())
                    tasks.add(anext_full)
                    
                    if stream_depth and anext_depth is None:
                        anext_depth = asyncio.ensure_future(stream_depth.__anext__())
                    if stream_depth:
                        tasks.add(anext_depth)
                        
                    done, _ = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    
                    if resync_task in done:
                        break
                        
                    if anext_full in done:
                        try:
                            pkt = anext_full.result()
                            anext_full = None
                            self._route(pkt)
                            consecutive_errors = 0
                        except StopAsyncIteration:
                            break
                            
                    if stream_depth and anext_depth in done:
                        try:
                            depth_obj = anext_depth.result()
                            anext_depth = None
                            self._route_depth(depth_obj)
                            consecutive_errors = 0
                        except (StopAsyncIteration, Exception) as depth_err:
                            if not isinstance(depth_err, StopAsyncIteration):
                                logger.debug("stream_depth ended (using stream_full 5-depth): %s", depth_err)
                            # Depth stream dead — drop cached 20-level books so
                            # ticks fall back to in-line 5-level depth.
                            self._depth_cache.clear()
                            stream_depth = None
                            anext_depth = None
                            
            except Exception as exc:
                if not self._stop.is_set():
                    consecutive_errors += 1
                    backoff = min(10.0, 1.0 * (1.5 ** min(consecutive_errors, 6)))
                    logger.warning(
                        "MultiplexedMarketFeed stream ended (%s): %s (retry in %.1fs)",
                        ",".join(symbols), exc, backoff,
                    )
                    await asyncio.sleep(backoff)
            finally:
                self._resync_async = None
                if stream_full is not None:
                    await self._aclose_quietly(stream_full)
                if stream_depth:
                    await self._aclose_quietly(stream_depth)

    @staticmethod
    async def _aclose_quietly(stream) -> None:
        try:
            await stream.aclose()
        except Exception:  # silent-except - best-effort stream close in shutdown
            pass

    # ------------------------------------------------------------------
    # Packet → per-symbol queue
    # ------------------------------------------------------------------

    def _route_depth(self, depth_obj) -> None:
        symbol = getattr(depth_obj, "symbol", None)
        if not symbol:
            return
        side = getattr(depth_obj, "side", "").lower()
        levels = getattr(depth_obj, "levels", [])
        if not levels:
            return
            
        if symbol not in self._depth_cache:
            self._depth_cache[symbol] = {"bids": [], "asks": [], "ts": 0.0}
            
        parsed_levels = [
            {"price": float(getattr(lvl, "price", 0)), "quantity": float(getattr(lvl, "quantity", 0))}
            for lvl in levels[:20]
        ]
        
        if side == "bid":
            self._depth_cache[symbol]["bids"] = parsed_levels
        elif side == "ask":
            self._depth_cache[symbol]["asks"] = parsed_levels
        self._depth_cache[symbol]["ts"] = time.time()

    def _put_tick(self, q: queue.Queue, tick: Tick) -> None:
        """Enqueue with drop-oldest when the bounded queue is full."""
        try:
            q.put_nowait(tick)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:  # silent-except - race: queue drained between Full and get
                pass
            try:
                q.put_nowait(tick)
            except queue.Full:  # silent-except - still full after drop; drop this tick
                pass

    def _route(self, pkt: dict) -> None:
        symbol = pkt.get("symbol") or pkt.get("_symbol")
        if not symbol:
            return
        tick = self._convert(pkt, symbol)
        if tick is None:
            return
        q = self._queues.get(symbol)
        if q is not None:
            self._put_tick(q, tick)
        for reader in tuple(self._readers.get(symbol, ())):
            self._put_tick(reader, tick)

    def _normalize_dhan_packet(self, pkt: dict, symbol: str) -> dict:
        """Translate Dhan-specific WebSocket packet fields to canonical names.
        
        This is the broker adapter layer within the multiplexer. All
        Dhan-proprietary field names and data transformations (cumulative →
        delta) are isolated here. _convert() reads only canonical fields.

        Baseline is NOT committed here — only after the packet survives
        validation in ``_convert`` (positive LTP, not late).
        """
        raw_vol = float(pkt.get("volume") or 0)
        raw_buy = float(pkt.get("total_buy_qty") or 0)
        raw_sell = float(pkt.get("total_sell_qty") or 0)
        baseline, (delta_vol, delta_buy, delta_sell) = self._cum_to_delta(
            self._prev_cum.get(symbol), raw_vol, raw_buy, raw_sell
        )
        return {
            "ltp": float(pkt.get("last_trade_price") or pkt.get("ltp") or pkt.get("LTP") or 0),
            "ltq": float(pkt.get("last_trade_quantity") or pkt.get("LTQ") or 0),
            "delta_volume": delta_vol,
            "bid_qty": delta_buy,
            "ask_qty": delta_sell,
            "_pending_baseline": baseline,
            "timestamp": (
                # Audit D-TIME-06: exchange event time (LTT epoch) is the truth
                # for bar windows. WSMessage.timestamp is datetime.now() on the
                # deployment machine — naive LOCAL wall clock — and preferring
                # it made bars follow the box's timezone and let the monotonic
                # guard discard ticks after NTP corrections. The real packet
                # shape carries this under "last_trade_time" (raw WS dict,
                # websocket_client.py) OR "ltt" (FullPacket field name after
                # streaming_service.py's rename / dhan_adapter's asdict()) —
                # both must be checked, or this silently degrades back to
                # wall-clock on every real production packet (re-audit finding:
                # the original fix only checked "last_trade_time", which never
                # survives the FullPacket rename). Fall back to the arrival
                # stamp only when the exchange sent neither.
                pkt.get("last_trade_time")
                or pkt.get("ltt")
                or pkt.get("LTP_time")
                or pkt.get("timestamp")
                or 0
            ),
            "oi": float(pkt.get("oi") or 0),
            "depth_bids": pkt.get("depth_bids") or [],
            "depth_asks": pkt.get("depth_asks") or [],
            "_raw_timestamp": (
                pkt.get("last_trade_time") or pkt.get("ltt") or pkt.get("timestamp")
            ),
        }

    def _convert(self, pkt: dict, symbol: str) -> Tick | None:
        """``symbol`` is resolved once by ``_route`` so the baseline key always
        matches the routing queue key."""
        try:
            norm_pkt = self._normalize_dhan_packet(pkt, symbol)
            
            ltp = norm_pkt["ltp"]
            if ltp <= 0:
                return None
            
            raw_ts = norm_pkt["_raw_timestamp"] or norm_pkt["timestamp"]
            if hasattr(raw_ts, "timestamp"):
                ts = float(raw_ts.timestamp())
            else:
                try:
                    ts = float(raw_ts or 0)
                except (ValueError, TypeError):
                    ts = 0.0

            used_arrival_clock = False
            if ts <= 0:
                # ponytail: poll-fallback packets carry ISO strings float()
                # rejects; ts=0 freezes bar windows so no bar closes and open
                # positions lose exit management. Arrival time keeps bars moving.
                ts = time.time()
                used_arrival_clock = True
            elif ts > time.time() + 10000:
                # Dhan binary protocol sends LTT pre-shifted by +IST (IST epoch).
                # Subtract one IST offset so ts is standard UTC epoch.
                ts -= _IST_OFFSET_SECONDS

            # Monotonic timestamp guard — discard out-of-order/late ticks silently.
            # Skip when using arrival clock so poll-fallback packets after a
            # real LTT packet are not all rejected as "late".
            prev_ts = self._prev_ts.get(symbol, 0.0)
            if not used_arrival_clock and ts > 0 and ts < prev_ts:
                logger.debug('Late tick discarded symbol=%s ts=%.3f prev=%.3f', symbol, ts, prev_ts)
                return None

            # Commit baselines only for packets that survive validation.
            pending = norm_pkt.get("_pending_baseline")
            if pending is not None:
                self._prev_cum[symbol] = pending
            if not used_arrival_clock and ts > 0:
                self._prev_ts[symbol] = ts

            dvol = norm_pkt["delta_volume"]
            
            # Buy/sell by tick direction (see ``_attr_delta``) — the book-total
            # diffs are noise and would fabricate the bar delta.
            prev_price = self._prev_price.get(symbol)
            self._prev_price[symbol] = ltp
            dbuy, dsell = self._attr_delta(prev_price, ltp, dvol)
            
            cached_depth = self._depth_cache.get(symbol)
            depth = None
            if cached_depth and (cached_depth.get("bids") or cached_depth.get("asks")):
                age = time.time() - float(cached_depth.get("ts") or 0.0)
                if age <= _DEPTH_CACHE_TTL_SEC:
                    depth = {
                        "bids": cached_depth["bids"],
                        "asks": cached_depth["asks"],
                    }
                else:
                    self._depth_cache.pop(symbol, None)
            if depth is None:
                db = norm_pkt["depth_bids"]
                da = norm_pkt["depth_asks"]
                if db or da:
                    depth = {
                        "bids": [
                            {"price": float(b["price"]), "quantity": float(b["qty"])}
                            for b in db[:20]
                        ],
                        "asks": [
                            {"price": float(a["price"]), "quantity": float(a["qty"])}
                            for a in da[:20]
                        ],
                    }
                    
            time_str = str(int(ts)) if ts > 0 else (str(int(raw_ts.timestamp())) if hasattr(raw_ts, "timestamp") else "0")
            return Tick(
                time=time_str,
                price=ltp,
                volume=dvol,
                buy_volume=dbuy,
                sell_volume=dsell,
                oi=norm_pkt["oi"],
                depth=depth,
            )
        except Exception:
            logger.exception("MultiplexedMarketFeed dropped packet: %r", pkt)
            return None
