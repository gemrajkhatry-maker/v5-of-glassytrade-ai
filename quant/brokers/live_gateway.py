"""Live gateway — pulls ticks from an IMarketData-compatible adapter.

Pure quant: imports ``quant.*`` + stdlib only. The adapter's ``stream_full``
(after async for over dict packets) is consumed on a daemon producer thread
and converted to ``Tick`` records for the engine's blocking ``next_tick()``.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading

from quant.brokers.gateway import Tick

logger = logging.getLogger(__name__)


class LiveGateway:
    """BrokerGateway protocol backed by a market-data adapter's stream_full."""

    def __init__(self, market_data, symbol: str) -> None:
        self._md = market_data
        self._symbol = symbol
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def subscribe(self, symbol: str) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._producer, args=(symbol,), daemon=True
        )
        self._thread.start()

    def next_tick(self) -> Tick | None:
        return self._queue.get()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._queue.put(None)

    def _producer(self, symbol: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._consume(symbol))
        except Exception:
            logger.exception("LiveGateway producer crashed for %s", symbol)
        finally:
            loop.close()
            self._queue.put(None)

    async def _consume(self, symbol: str) -> None:
        try:
            async for pkt in self._md.stream_full([symbol]):
                if self._stop.is_set():
                    return
                tick = self._convert(pkt)
                if tick is not None:
                    self._queue.put(tick)
        except Exception as exc:
            if not self._stop.is_set():
                logger.warning("LiveGateway stream for %s ended: %s", symbol, exc)

    @staticmethod
    def _convert(pkt: dict) -> Tick | None:
        try:
            ltp = float(pkt.get("ltp") or 0)
            if ltp <= 0:
                return None
            depth = None
            db = pkt.get("depth_bids") or []
            da = pkt.get("depth_asks") or []
            if db or da:
                depth = {
                    "bids": [[float(b["price"]), float(b["qty"])] for b in db[:5]],
                    "asks": [[float(a["price"]), float(a["qty"])] for a in da[:5]],
                }
            return Tick(
                time=str(int(pkt["timestamp"].timestamp())),
                price=ltp,
                volume=float(pkt.get("volume") or 0),
                buy_volume=float(pkt.get("total_buy_qty") or 0),
                sell_volume=float(pkt.get("total_sell_qty") or 0),
                oi=float(pkt.get("oi") or 0),
                depth=depth,
            )
        except Exception:
            logger.exception("LiveGateway dropped packet: %r", pkt)
            return None
