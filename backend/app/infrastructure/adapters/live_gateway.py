"""Live market-data gateway bridging Dhan stream_full packets to quant ticks."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading

from quant.brokers.gateway import Tick

logger = logging.getLogger(__name__)


class LiveGateway:
    """BrokerGateway backed by a DhanMarketDataAdapter streaming thread."""

    def __init__(self, dhan_adapter, symbol: str) -> None:
        self._dhan = dhan_adapter
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
            logger.exception("LiveGateway producer crashed")
        finally:
            loop.close()
            self._queue.put(None)

    async def _consume(self, symbol: str) -> None:
        retries = 0
        prev_vol = prev_buy = prev_sell = None
        while not self._stop.is_set():
            try:
                async for pkt in self._dhan.stream_full([symbol]):
                    if self._stop.is_set():
                        return
                    tick, prev_vol, prev_buy, prev_sell = self._convert(
                        pkt, prev_vol, prev_buy, prev_sell
                    )
                    if tick is not None:
                        self._queue.put(tick)
                    retries = 0
                if self._stop.is_set():
                    return
                raise ConnectionError("stream ended")
            except Exception as e:
                if self._stop.is_set():
                    return
                logger.warning("LiveGateway stream interrupted, reconnecting: %s", e)
                prev_vol = prev_buy = prev_sell = None
                retries += 1
                if retries > 3:
                    logger.error(
                        "LiveGateway giving up after %d consecutive failures", retries
                    )
                    return
                delay = min(5 * 2 ** (retries - 1), 60)
                for _ in range(int(delay * 4)):
                    if self._stop.is_set():
                        break
                    await asyncio.sleep(0.25)

    def _convert(self, pkt, prev_vol, prev_buy, prev_sell):
        try:
            ltq = float(pkt.get("ltq") or 0)
            cum_vol = float(pkt.get("volume") or 0)
            cum_buy = float(pkt.get("total_buy_qty") or 0)
            cum_sell = float(pkt.get("total_sell_qty") or 0)

            if ltq > 0:
                volume = ltq
            elif prev_vol is not None:
                volume = max(0.0, cum_vol - prev_vol)
            else:
                volume = 0.0

            buy_volume = max(0.0, cum_buy - prev_buy) if prev_buy is not None else 0.0
            sell_volume = (
                max(0.0, cum_sell - prev_sell) if prev_sell is not None else 0.0
            )

            tick = Tick(
                time=str(int(pkt["timestamp"].timestamp())),
                price=float(pkt["ltp"]),
                volume=volume,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
            )
            return tick, cum_vol, cum_buy, cum_sell
        except Exception:
            logger.exception("LiveGateway dropped packet: %r", pkt)
            return None, prev_vol, prev_buy, prev_sell
