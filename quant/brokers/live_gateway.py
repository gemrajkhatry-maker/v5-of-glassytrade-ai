"""Live gateway — per-symbol reader over the shared MultiplexedMarketFeed.

The coordinator owns ONE :class:`MultiplexedMarketFeed` (single WebSocket,
single producer thread, single event loop) and hands each engine a thin
``LiveGateway`` view for its own symbol. This guarantees at most one
market-data WebSocket connection regardless of how many instruments are
subscribed (Dhan supports up to 1000 per connection).

Pure quant: imports ``quant.*`` + stdlib only.
"""

from __future__ import annotations

from quant.brokers.gateway import Tick
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed


class LiveGateway:
    """BrokerGateway protocol backed by a shared MultiplexedMarketFeed."""

    def __init__(self, feed: MultiplexedMarketFeed, symbol: str, reader_queue=None) -> None:
        self._feed = feed
        self._symbol = symbol
        self._reader_queue = reader_queue

    def subscribe(self, symbol: str) -> None:
        self._feed.subscribe(symbol)

    def next_tick(self) -> Tick | None:
        return self._reader_queue.get() if self._reader_queue is not None else self._feed.next_tick(self._symbol)

    def close(self) -> None:
        if self._reader_queue is not None:
            self._feed.remove_reader(self._symbol, self._reader_queue)
        else:
            self._feed.unsubscribe(self._symbol)
