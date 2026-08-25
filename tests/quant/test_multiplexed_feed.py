"""Tests for MultiplexedMarketFeed — one WebSocket, many symbols.

Verifies the core invariants of the single-connection feed:
* ``set_symbols([...])`` issues ONE ``stream_full`` call with the full set.
* packets are demultiplexed by ``symbol`` into per-symbol queues.
* each symbol's ``next_tick`` only ever yields its own ticks.
* subscribing a new symbol resyncs the stream (no new connection).
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone

from quant.brokers.gateway import Tick
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed


def _ts(sec: int) -> datetime:
    return datetime(2026, 8, 7, 10, 0, sec, tzinfo=timezone.utc)


class _FakeMarketData:
    """Records every stream_full call + the symbol list it was given.

    Mirrors the real Dhan stream: yields the fixture packets, then stays
    open (like a persistent WebSocket) until the feed's stop event fires.
    """

    def __init__(self, packets_by_symbol: dict[str, list[dict]]):
        self._packets = packets_by_symbol
        self.calls: list[list[str]] = []
        self.stop: threading.Event | None = None  # wired to feed._stop by _make_feed

    async def stream_full(self, symbols: list[str]):
        self.calls.append(list(symbols))
        for sym in symbols:
            for pkt in self._packets.get(sym, []):
                yield pkt
        # keep the connection "open" until the feed is closed
        while self.stop is None or not self.stop.is_set():
            await asyncio.sleep(0.02)


def _pkt(symbol: str, sec: int, ltp: float, volume: float = 10.0) -> dict:
    return {
        "symbol": symbol,
        "timestamp": _ts(sec),
        "ltp": ltp,
        "volume": volume,
        "total_buy_qty": 5.0,
        "total_sell_qty": 3.0,
        "oi": 123.0,
    }


def _make_feed(md: _FakeMarketData) -> MultiplexedMarketFeed:
    feed = MultiplexedMarketFeed(md)
    md.stop = feed._stop  # wire keep-alive to the feed's stop event
    return feed


def _wait_until(fn, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not fn():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.01)


def test_set_symbols_issues_single_stream_full_call():
    md = _FakeMarketData({
        "A": [_pkt("A", 1, 100.0)],
        "B": [_pkt("B", 1, 200.0)],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A", "B"])
    try:
        _wait_until(lambda: len(md.calls) >= 1)
        time.sleep(0.1)  # allow any accidental extra calls to surface
        assert len(md.calls) == 1, f"expected a single stream_full call, got {md.calls}"
        assert set(md.calls[0]) == {"A", "B"}
    finally:
        feed.close()


def test_packets_demuxed_into_per_symbol_queues():
    md = _FakeMarketData({
        "A": [_pkt("A", 1, 100.0), _pkt("A", 2, 101.0)],
        "B": [_pkt("B", 1, 200.0)],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A", "B"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 2)
        _wait_until(lambda: feed._queues["B"].qsize() >= 1)

        a0 = feed.next_tick("A")
        a1 = feed.next_tick("A")
        b0 = feed.next_tick("B")

        assert isinstance(a0, Tick) and isinstance(a1, Tick) and isinstance(b0, Tick)
        assert a0.price == 100.0
        assert a1.price == 101.0
        assert b0.price == 200.0
        # A never receives B's tick and vice versa
        assert feed._queues["A"].qsize() == 0
        assert feed._queues["B"].qsize() == 0
    finally:
        feed.close()


def test_reader_receives_copy_without_stealing_primary_tick():
    md = _FakeMarketData({"FUT": [_pkt("FUT", 1, 100.0)]})
    feed = _make_feed(md)
    reader = feed.add_reader("FUT")
    feed.set_symbols(["FUT"])
    try:
        _wait_until(lambda: feed._queues["FUT"].qsize() >= 1 and reader.qsize() >= 1)
        assert feed.next_tick("FUT").price == 100.0
        assert reader.get().price == 100.0
    finally:
        feed.remove_reader("FUT", reader)
        feed.close()


def test_cumulative_volume_converted_to_per_tick_delta():
    """Dhan WS volume is cumulative — ticks must carry per-tick deltas.

    The aggregator sums tick volumes, so feeding it raw cumulative values
    would explode bar volume (the flat/misleading volume regression). The
    feed must emit ``vol - prev_cum`` with a session-reset guard. Buy/sell
    are attributed by tick direction (up-tick = buy), NOT by the order-book
    total diffs, which oscillate and would fabricate the bar delta.
    """
    md = _FakeMarketData({
        "A": [
            {**_pkt("A", 1, 100.0), "volume": 100, "total_buy_qty": 60,
             "total_sell_qty": 40},
            {**_pkt("A", 2, 101.0), "volume": 150, "total_buy_qty": 90,
             "total_sell_qty": 60},
            {**_pkt("A", 3, 102.0), "volume": 155, "total_buy_qty": 92,
             "total_sell_qty": 63},
        ],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 3)
        t1 = feed.next_tick("A")
        t2 = feed.next_tick("A")
        t3 = feed.next_tick("A")
        # First packet establishes the volume baseline (delta 0) and has no
        # direction yet — buy/sell split evenly on zero volume.
        assert t1.volume == 0.0 and t1.buy_volume == 0.0 and t1.sell_volume == 0.0
        # Subsequent packets carry the cumulative difference, attributed by
        # tick direction: 100 → 101 → 102 is a string of up-ticks (buy).
        assert t2.volume == 50.0 and t2.buy_volume == 50.0 and t2.sell_volume == 0.0
        assert t3.volume == 5.0 and t3.buy_volume == 5.0 and t3.sell_volume == 0.0
        # Prices always flow regardless of volume baseline.
        assert t1.price == 100.0 and t2.price == 101.0 and t3.price == 102.0
    finally:
        feed.close()


def test_delta_attributed_by_tick_direction():
    """Buy/sell must come from price direction, not order-book totals.

    Dhan's total_buy_qty/total_sell_qty are CURRENT order-book bid/ask
    totals — their diffs oscillate with every book change and would produce a
    fabricated bar delta (the live GOLDM bar showed delta=+82 vs the
    exchange's real +10). Attribution: up-tick → buy, down-tick → sell,
    flat tick → split, and buy+sell always equals the tick's volume.
    """
    md = _FakeMarketData({
        "A": [
            {**_pkt("A", 1, 100.0), "volume": 100},
            {**_pkt("A", 2, 101.0), "volume": 108},   # up-tick → buy 8
            {**_pkt("A", 3, 100.5), "volume": 113},   # down-tick → sell 5
            {**_pkt("A", 4, 100.5), "volume": 117},   # flat → split 4/4
        ],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 4)
        t1 = feed.next_tick("A")
        t2 = feed.next_tick("A")
        t3 = feed.next_tick("A")
        t4 = feed.next_tick("A")
        # First tick: no direction yet — split evenly (4 of the 8).
        assert t1.volume == 0.0
        assert t2.volume == 8.0 and t2.buy_volume == 8.0 and t2.sell_volume == 0.0
        assert t3.volume == 5.0 and t3.buy_volume == 0.0 and t3.sell_volume == 5.0
        assert t4.volume == 4.0 and t4.buy_volume == 2.0 and t4.sell_volume == 2.0
        # buy + sell == volume on every tick (consistency invariant).
        for t in (t2, t3, t4):
            assert abs(t.buy_volume + t.sell_volume - t.volume) < 1e-9
    finally:
        feed.close()


def test_oscillating_buy_sell_does_not_reset_baseline():
    """Dhan total_buy_qty/total_sell_qty are book totals that oscillate.

    Only cumulative `volume` is monotonic — the session-reset guard must not
    look at buy/sell, or it trips on nearly every packet and the bar loses
    ~85% of its traded volume (the V=410020-vs-10M distortion). Buy/sell on
    the tick come from price direction, so the oscillating book totals must
    never influence volume OR the delta.
    """
    md = _FakeMarketData({
        "A": [
            {**_pkt("A", 1, 100.0), "volume": 100, "total_buy_qty": 60,
             "total_sell_qty": 40},
            # buy/sell go DOWN — but volume keeps rising: NOT a reset
            {**_pkt("A", 2, 101.0), "volume": 150, "total_buy_qty": 55,
             "total_sell_qty": 42},
            {**_pkt("A", 3, 102.0), "volume": 165, "total_buy_qty": 62,
             "total_sell_qty": 35},
        ],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 3)
        t1 = feed.next_tick("A")
        t2 = feed.next_tick("A")
        t3 = feed.next_tick("A")
        # Volume accumulates fully across oscillating buy/sell: 0, +50, +15.
        assert t1.volume == 0.0
        assert t2.volume == 50.0
        assert t3.volume == 15.0
        # Rising prices → all buys, regardless of the oscillating book totals.
        assert t2.buy_volume == 50.0 and t2.sell_volume == 0.0
        assert t3.buy_volume == 15.0 and t3.sell_volume == 0.0
    finally:
        feed.close()


def test_no_volume_ticker_packet_does_not_reset_baseline():
    """A TICKER packet (LTP only, no volume fields) must not re-baseline.

    If vol=0 were treated as a reset, the next real packet's delta (full
    cumulative vs 0) would be capped at 10k, losing almost all bar volume.
    """
    md = _FakeMarketData({
        "A": [
            {**_pkt("A", 1, 100.0), "volume": 100, "total_buy_qty": 60,
             "total_sell_qty": 40},
            {**_pkt("A", 2, 101.0), "volume": 0, "total_buy_qty": 0,
             "total_sell_qty": 0},  # ticker — no volume data
            {**_pkt("A", 3, 102.0), "volume": 190, "total_buy_qty": 61,
             "total_sell_qty": 41},
        ],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 3)
        t1 = feed.next_tick("A")
        t2 = feed.next_tick("A")
        t3 = feed.next_tick("A")
        assert t1.volume == 0.0
        assert t2.volume == 0.0   # ticker contributes nothing
        # The next real packet gets the TRUE delta (90), not a 10k-capped
        # full-cumulative spike (which would be ~100 minus baseline 0).
        assert t3.volume == 90.0
    finally:
        feed.close()


def test_cumulative_session_reset_rebaselines():
    """A cumulative value going backwards = session reset → delta 0, re-baseline."""
    md = _FakeMarketData({
        "A": [
            {**_pkt("A", 1, 100.0), "volume": 100},
            {**_pkt("A", 2, 101.0), "volume": 150},
            {**_pkt("A", 3, 102.0), "volume": 10},  # reset (dropped below prev)
            {**_pkt("A", 4, 103.0), "volume": 25},
        ],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 4)
        t1 = feed.next_tick("A")
        t2 = feed.next_tick("A")
        t3 = feed.next_tick("A")
        t4 = feed.next_tick("A")
        assert t1.volume == 0.0
        assert t2.volume == 50.0
        assert t3.volume == 0.0   # reset tick dropped
        assert t4.volume == 15.0  # re-baselined at 10
    finally:
        feed.close()


def test_next_tick_returns_none_for_unsubscribed_symbol():
    md = _FakeMarketData({"A": [_pkt("A", 1, 100.0)]})
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        assert feed.next_tick("MISSING") is None
    finally:
        feed.close()


def test_subscribe_new_symbol_resyncs_stream():
    md = _FakeMarketData({
        "A": [_pkt("A", 1, 100.0)],
        "B": [_pkt("B", 1, 200.0)],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: len(md.calls) >= 1)
        assert set(md.calls[0]) == {"A"}

        feed.subscribe("B")  # new symbol → resync → re-subscribe with both
        _wait_until(lambda: len(md.calls) >= 2)
        # latest call carries both symbols (B added on the same connection)
        assert set(md.calls[-1]) == {"A", "B"}
        _wait_until(lambda: feed._queues["B"].qsize() >= 1)
        assert feed.next_tick("B").price == 200.0
    finally:
        feed.close()


def test_unsubscribe_stops_routing_for_symbol():
    md = _FakeMarketData({
        "A": [_pkt("A", 1, 100.0), _pkt("A", 2, 101.0), _pkt("A", 3, 102.0)],
    })
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 2)
        feed.unsubscribe("A")
        assert feed.next_tick("A") is None  # blocked reader woken with None
    finally:
        feed.close()


def test_close_wakes_blocked_readers():
    # Symbol "A" has NO packets — the reader is genuinely blocked on q.get()
    # and can only be released by close()'s None sentinel.
    md = _FakeMarketData({"A": []})
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    result: list = []

    def reader():
        result.append(feed.next_tick("A"))

    t = threading.Thread(target=reader)
    t.start()
    try:
        _wait_until(lambda: t.is_alive())  # reader parked on q.get()
        feed.close()
        t.join(timeout=2.0)
        assert not t.is_alive(), "close() must wake a blocked reader with None"
        assert result == [None]
    finally:
        if t.is_alive():
            feed.close()
            t.join(timeout=1.0)


def test_close_wakes_blocked_dedicated_reader():
    feed = _make_feed(_FakeMarketData({"FUT": []}))
    reader = feed.add_reader("FUT")
    result: list = []

    def read_dedicated_queue():
        result.append(reader.get())

    t = threading.Thread(target=read_dedicated_queue)
    t.start()
    try:
        _wait_until(t.is_alive)
        feed.close()
        t.join(timeout=2.0)
        assert not t.is_alive(), "close() must wake a dedicated reader with None"
        assert result == [None]
    finally:
        feed.remove_reader("FUT", reader)
        t.join(timeout=1.0)
        feed.close()


def test_producer_survives_stream_factory_failure():
    """A raising stream_full must trigger retry, not kill the producer thread."""
    import time as _time
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    class _FlakyMD:
        def __init__(self):
            self.calls = 0

        def stream_full(self, symbols):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("broker down")

            async def _gen():
                yield {"symbol": symbols[0], "last_trade_price": 100.0,
                       "volume": 5, "ltt": 1786095001}

            return _gen()

    md = _FlakyMD()
    feed = MultiplexedMarketFeed(md)
    feed.set_symbols(["TEST FUT"])
    tick = None
    deadline = _time.time() + 15
    while _time.time() < deadline:
        tick = feed.try_next_tick("TEST FUT")
        if tick is not None:
            break
        _time.sleep(0.05)
    feed.close()
    assert md.calls >= 2, "producer died instead of retrying"
    assert tick is not None and tick.price == 100.0


def test_convert_iso_timestamp_does_not_produce_zero_time():
    """Poll-fallback packets carry ISO strings; ts must not collapse to '0'
    (a zero epoch freezes bar windows and disables exits)."""
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    pkt = {"symbol": "TEST FUT", "last_trade_price": 100.0, "volume": 5,
           "timestamp": "2026-08-25T10:00:00"}
    tick = feed._convert(pkt, "TEST FUT")
    assert tick is not None
    assert tick.time != "0"
    assert float(tick.time) > 946684800  # post-2000 epoch
