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

from quant.brokers.gateway import Tick

logger = logging.getLogger(__name__)


class MultiplexedMarketFeed:
    """Single-connection, multi-symbol market feed with per-symbol queues."""

    def __init__(self, market_data) -> None:
        self._md = market_data
        self._queues: dict[str, queue.Queue] = {}
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
        # Lock discipline: the producer thread is the SOLE writer of this dict
        # (``_route``/``_convert`` run single-threaded on the producer).
        # ``unsubscribe``/``close`` pop/clear entries under ``self._lock``;
        # dict reads and writes are GIL-atomic, so a pop racing a write can
        # only drop a baseline (benign — the next packet re-baselines). Do not
        # "fix" one side to take the lock without taking it on the other.
        self._prev_cum: dict[str, tuple[float, float, float]] = {}

    # ------------------------------------------------------------------
    # Cumulative -> per-tick delta conversion (legacy candle-builder logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _cum_to_delta(
        prev: tuple[float, float, float] | None,
        vol: float, buy: float, sell: float,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return ``(new_baseline, (dvol, dbuy, dsell))`` for a packet.

        First packet for a symbol establishes the baseline (delta 0). A
        value that went *backwards* means a session reset — re-baseline,
        drop the spike. A delta larger than 5% of the baseline (or 10k) is
        treated as a stale/session-reset artifact and capped — mirrors the
        legacy ``candle_aggregator`` caps (``vol_cap`` and combined
        ``bs_cap`` for buy/sell).
        """
        if prev is None:
            return (vol, buy, sell), (0.0, 0.0, 0.0)
        pvol, pbuy, psell = prev
        if vol < pvol or buy < pbuy or sell < psell:
            return (vol, buy, sell), (0.0, 0.0, 0.0)
        dvol = max(0.0, vol - pvol)
        dbuy = max(0.0, buy - pbuy)
        dsell = max(0.0, sell - psell)
        cap = max(10000.0, pvol * 0.05) if pvol > 0 else 10000.0
        if dvol > cap:
            dvol = cap
        bs_tot = pbuy + psell
        bs_cap = max(10000.0, bs_tot * 0.05) if bs_tot > 0 else 10000.0
        if dbuy > bs_cap:
            dbuy = bs_cap
        if dsell > bs_cap:
            dsell = bs_cap
        return (vol, buy, sell), (dvol, dbuy, dsell)

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
                self._queues.setdefault(sym, queue.Queue())
            changed = set(symbols) != before
        self._kick(changed=changed)

    def subscribe(self, symbol: str) -> None:
        """Register one symbol (idempotent). Resyncs only if it is new."""
        with self._lock:
            fresh = symbol not in self._queues
            self._queues.setdefault(symbol, queue.Queue())
        self._kick(changed=fresh)

    def unsubscribe(self, symbol: str) -> None:
        """Drop a symbol's queue and unblock any reader blocked on it."""
        with self._lock:
            q = self._queues.pop(symbol, None)
            self._prev_cum.pop(symbol, None)
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

    def close(self) -> None:
        """Stop the producer thread and unblock every reader."""
        self._stop.set()
        self._wake_loop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with self._lock:
            self._prev_cum.clear()
            for q in self._queues.values():
                q.put(None)

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
        while not self._stop.is_set():
            symbols = self._snapshot_symbols()
            if not symbols:
                await asyncio.sleep(0.5)
                continue
            # Honor a pending resync BEFORE clearing it: if a symbol was added
            # in the window where the cross-thread wake couldn't fire yet, the
            # threading.Event still holds the signal — don't discard it.
            pending = self._resync.is_set()
            self._resync_async = asyncio.Event()
            if pending:
                self._resync_async.set()
            self._resync.clear()
            stream = self._md.stream_full(symbols)
            try:
                while True:
                    if self._stop.is_set() or self._resync.is_set():
                        break
                    anext_task = asyncio.ensure_future(stream.__anext__())
                    resync_task = asyncio.ensure_future(
                        self._resync_async.wait()
                    )
                    done, _ = await asyncio.wait(
                        {anext_task, resync_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if anext_task in done:
                        resync_task.cancel()
                        try:
                            pkt = anext_task.result()
                        except StopAsyncIteration:
                            break
                        self._route(pkt)
                        continue
                    # resync fired — abandon this stream, resubscribe next loop
                    anext_task.cancel()
                    try:
                        await anext_task
                    except (asyncio.CancelledError, StopAsyncIteration):
                        pass
                    break
            except Exception as exc:
                if not self._stop.is_set():
                    logger.warning(
                        "MultiplexedMarketFeed stream ended (%s): %s",
                        ",".join(symbols), exc,
                    )
                    await asyncio.sleep(1.0)
            finally:
                self._resync_async = None
                await self._aclose_quietly(stream)

    @staticmethod
    async def _aclose_quietly(stream) -> None:
        try:
            await stream.aclose()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Packet → per-symbol queue
    # ------------------------------------------------------------------

    def _route(self, pkt: dict) -> None:
        symbol = pkt.get("symbol") or pkt.get("_symbol")
        if not symbol:
            return
        tick = self._convert(pkt, symbol)
        if tick is None:
            return
        q = self._queues.get(symbol)
        if q is not None:
            q.put(tick)

    def _convert(self, pkt: dict, symbol: str) -> Tick | None:
        """``symbol`` is resolved once by ``_route`` so the baseline key always
        matches the routing queue key."""
        try:
            ltp = float(pkt.get("ltp") or 0)
            if ltp <= 0:
                return None
            vol = float(pkt.get("volume") or 0)
            buy = float(pkt.get("total_buy_qty") or 0)
            sell = float(pkt.get("total_sell_qty") or 0)
            baseline, (dvol, dbuy, dsell) = self._cum_to_delta(
                self._prev_cum.get(symbol), vol, buy, sell
            )
            self._prev_cum[symbol] = baseline
            depth = None
            db = pkt.get("depth_bids") or []
            da = pkt.get("depth_asks") or []
            if db or da:
                # Object shape matches the legacy ``order_book_to_dto``
                # contract the frontend OrderBook type expects.
                depth = {
                    "bids": [
                        {"price": float(b["price"]), "quantity": float(b["qty"])}
                        for b in db[:5]
                    ],
                    "asks": [
                        {"price": float(a["price"]), "quantity": float(a["qty"])}
                        for a in da[:5]
                    ],
                }
            return Tick(
                time=str(int(pkt["timestamp"].timestamp())),
                price=ltp,
                volume=dvol,
                buy_volume=dbuy,
                sell_volume=dsell,
                oi=float(pkt.get("oi") or 0),
                depth=depth,
            )
        except Exception:
            logger.exception("MultiplexedMarketFeed dropped packet: %r", pkt)
            return None
