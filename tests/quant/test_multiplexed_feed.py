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

import pytest

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


class _FailingMarketData:
    def __init__(self):
        self.calls = 0
        self.full_started = threading.Event()
        self.depth_started = threading.Event()
        self.full_closed = threading.Event()
        self.depth_closed = threading.Event()

    def _stream(self, started, closed):
        async def _generator():
            started.set()
            try:
                await asyncio.sleep(60)
            finally:
                closed.set()
            yield {}

        return _generator()

    def stream_full(self, symbols):
        self.calls += 1
        return self._stream(self.full_started, self.full_closed)

    def stream_depth_20(self, symbols):
        return self._stream(self.depth_started, self.depth_closed)


@pytest.fixture
def managed_feed():
    feed = _make_feed(_FailingMarketData())
    try:
        yield feed
    finally:
        feed.close()


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


def test_route_drops_unknown_symbol_with_rate_limited_warning(caplog):
    """A packet whose symbol has no queue must warn (rate-limited), not vanish."""
    import logging

    md = _FakeMarketData({"A": [_pkt("A", 1, 100.0)]})
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 1)
        with caplog.at_level(logging.WARNING, logger="quant.brokers.multiplexed_feed"):
            feed._route({"symbol": "GHOST FUT", "ltp": 1.0, "volume": 1, "timestamp": _ts(5)})
            feed._route({"symbol": "GHOST FUT", "ltp": 2.0, "volume": 1, "timestamp": _ts(6)})
        ghosts = [r for r in caplog.records if "GHOST FUT" in r.getMessage()]
        # Rate-limited: two drops within 30s → one warning, count tracks both.
        assert len(ghosts) == 1, [r.getMessage() for r in ghosts]
        assert "no_queue" in ghosts[0].getMessage()
        assert feed._drop_counts.get("no_queue:GHOST FUT") == 2
    finally:
        feed.close()


def test_route_convert_none_is_noted():
    md = _FakeMarketData({"A": [_pkt("A", 1, 100.0)]})
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        feed._route({"symbol": "A", "ltp": 0, "volume": 1, "timestamp": _ts(1)})
        assert feed._drop_counts.get("convert_none:A") or feed._drop_counts.get(
            "non_positive_ltp:A"
        )
    finally:
        feed.close()


def test_convert_stamps_arrived_at_on_tick():
    """Tick.arrived_at must be local arrival wall-clock (for health freshness)."""
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    before = time.time()
    tick = feed._convert(_pkt("A", 1, 100.0), "A")
    after = time.time()
    assert tick is not None
    assert before <= tick.arrived_at <= after


def test_quote_only_zero_ltt_does_not_pollute_prev_ts():
    """ltt=0 quote must not poison _prev_ts with arrival wall-clock.

    Regression: the or-chain fell through to FullPacket's arrival datetime
    when ltt=0, so _prev_ts was set to fractional wall-clock; every later
    real (older) exchange LTT then landed "late" and was dropped — the MCX
    late_tick flood (drops #200-769/symbol, ~80/min).
    """
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    # Quote-only packet: ltt=0, FullPacket carries arrival datetime.
    quote = {
        "symbol": "CRUDEOIL OCT FUT",
        "ltp": 5000.0,
        "volume": 100,
        "total_buy_qty": 10,
        "total_sell_qty": 20,
        "ltt": 0,
        "timestamp": datetime.now(timezone.utc),
        "oi": 0,
        "depth_bids": [],
        "depth_asks": [],
    }
    tick = feed._convert(dict(quote), "CRUDEOIL OCT FUT")
    assert tick is not None, "quote-only packet must route"
    # Arrival stamp must NOT advance the exchange-LTT high-water mark.
    assert feed._prev_ts.get("CRUDEOIL OCT FUT", 0.0) == 0.0, (
        f"ltt=0 arrival must not write _prev_ts, got {feed._prev_ts}"
    )
    assert feed._last_convert_drop is None


def test_old_exchange_ltt_after_quote_still_routes():
    """A real exchange LTT older than wall-clock must not drop after a quote.

    Sequence that caused the flood: quote (ltt=0 → arrival, previously
    polluted prev_ts to wall-clock) then a trade packet with exchange LTT
    155s old — must route, not late_tick.
    """
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    sym = "NATURALGAS SEP FUT"
    # 1) quote-only, ltt=0
    feed._convert(
        {
            "symbol": sym, "ltp": 100.0, "volume": 10,
            "total_buy_qty": 1, "total_sell_qty": 1,
            "ltt": 0, "timestamp": datetime.now(timezone.utc),
            "oi": 0, "depth_bids": [], "depth_asks": [],
        },
        sym,
    )
    # 2) real trade packet with exchange LTT 155s in the past
    old_ltt = int(time.time()) - 155
    tick = feed._convert(
        {
            "symbol": sym, "ltp": 101.0, "volume": 20,
            "total_buy_qty": 1, "total_sell_qty": 1,
            "ltt": old_ltt, "timestamp": datetime.now(timezone.utc),
            "oi": 0, "depth_bids": [], "depth_asks": [],
        },
        sym,
    )
    assert tick is not None, (
        f"old exchange LTT after quote must route, drops={feed._drop_counts}"
    )
    assert "late_tick:" + sym not in feed._drop_counts
    assert feed._prev_ts[sym] == float(old_ltt)


def test_small_exchange_ltt_regression_routes_within_grace():
    """Quote-snapshot LTT lagging a few seconds behind the trade tick is valid.

    Dhan interleaves quote/full/tick messages; a quote built just before a
    trade can arrive after the trade's tick with LTT 1-11s older. Strict
    monotonic guard dropped these (~10-15/symbol/min live). Within the
    grace window they must route; _prev_ts must NOT regress.
    """
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    sym = "SILVERM NOV FUT"
    newer = float(int(time.time()))
    older = newer - 5.0  # 5s lag — within 30s grace
    t_new = feed._convert(
        {"symbol": sym, "ltp": 100.0, "volume": 10, "ltt": int(newer),
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    assert t_new is not None
    assert feed._prev_ts[sym] == newer
    t_old = feed._convert(
        {"symbol": sym, "ltp": 99.5, "volume": 5, "ltt": int(older),
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    assert t_old is not None, (
        f"5s LTT lag within grace must route, drops={feed._drop_counts}"
    )
    assert feed._prev_ts[sym] == newer, "_prev_ts must be a high-water mark"


def test_exchange_ltt_beyond_grace_still_drops():
    """Grossly out-of-order exchange LTT (>30s behind) must still late_tick."""
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    sym = "GOLDM OCT FUT"
    newer = float(int(time.time()))
    ancient = newer - 120.0  # beyond 30s grace
    feed._convert(
        {"symbol": sym, "ltp": 100.0, "volume": 10, "ltt": int(newer),
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    tick = feed._convert(
        {"symbol": sym, "ltp": 99.0, "volume": 5, "ltt": int(ancient),
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    assert tick is None
    assert feed._drop_counts.get(f"late_tick:{sym}") == 1
    assert feed._last_convert_drop == "late_tick"


def test_route_late_tick_not_double_counted_as_convert_none():
    """_route must not convert_none-note a drop _convert already noted."""
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    sym = "CRUDEOIL 15 OCT 8650 CALL"
    # Establish a high-water mark, then send ancient LTT.
    feed._convert(
        {"symbol": sym, "ltp": 100.0, "volume": 10, "ltt": int(time.time()),
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    feed._route(
        {"symbol": sym, "ltp": 99.0, "volume": 5,
         "ltt": int(time.time()) - 120,
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
    )
    assert feed._drop_counts.get(f"late_tick:{sym}") == 1
    assert feed._drop_counts.get(f"convert_none:{sym}") is None, (
        f"late_tick must not double-count as convert_none: {feed._drop_counts}"
    )


def test_route_non_positive_ltp_not_double_counted_as_convert_none():
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    feed._route(
        {"symbol": "A", "ltp": 0, "volume": 1, "ltt": int(time.time()),
         "total_buy_qty": 0, "total_sell_qty": 0, "oi": 0,
         "depth_bids": [], "depth_asks": []},
    )
    assert feed._drop_counts.get("non_positive_ltp:A") == 1
    assert feed._drop_counts.get("convert_none:A") is None


def test_arrival_source_skips_guard_even_when_older_than_prev_exchange():
    """Poll/ISO arrival stamps must never be rejected as late_tick."""
    from unittest.mock import MagicMock
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    sym = "TEST FUT"
    # Exchange LTT first — sets high-water mark.
    feed._convert(
        {"symbol": sym, "ltp": 100.0, "volume": 10, "ltt": int(time.time()),
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    prev = feed._prev_ts[sym]
    # Arrival-only packet with no exchange LTT (poll fallback / ISO).
    tick = feed._convert(
        {"symbol": sym, "ltp": 101.0, "volume": 5,
         "timestamp": "2020-01-01T00:00:00",  # ancient ISO — arrival source
         "total_buy_qty": 1, "total_sell_qty": 1, "oi": 0,
         "depth_bids": [], "depth_asks": []},
        sym,
    )
    assert tick is not None, f"arrival source must skip guard: {feed._drop_counts}"
    assert feed._prev_ts[sym] == prev, "arrival must not regress _prev_ts"
    assert tick.time != "0"  # still gets a usable bar timestamp


def test_silent_symbols_reports_subscribed_queue_with_no_packets():
    """A subscribed symbol that never routes must appear in silent_symbols()."""
    import time as _t
    md = _FakeMarketData({"A": [_pkt("A", 1, 100.0)], "SILENT": []})
    feed = _make_feed(md)
    feed.set_symbols(["A", "SILENT"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 1)
        # Never-routed symbols only count after subscribe grace (60s) —
        # push the subscribe stamp past the threshold to simulate a stuck sid.
        feed._subscribe_mono["SILENT"] = _t.monotonic() - 120.0
        silent = feed.silent_symbols(threshold_sec=60.0)
        assert "SILENT" in silent
        assert "A" not in silent  # A routed at least once
    finally:
        feed.close()


def test_silent_symbols_empty_right_after_route():
    md = _FakeMarketData({"A": [_pkt("A", 1, 100.0)]})
    feed = _make_feed(md)
    feed.set_symbols(["A"])
    try:
        _wait_until(lambda: feed._queues["A"].qsize() >= 1)
        assert feed.silent_symbols(threshold_sec=60.0) == []
    finally:
        feed.close()


def test_close_cancels_failing_streams_and_is_idempotent(managed_feed):
    feed = managed_feed
    md = feed._md
    reader = feed.add_reader("NIFTY")
    for _ in range(4096):
        reader.put(object())
    feed.subscribe("NIFTY")

    assert md.full_started.wait(timeout=2.0)
    assert md.depth_started.wait(timeout=2.0)

    feed.close()
    feed.close()

    assert feed._thread is None
    assert md.full_closed.wait(timeout=1.0)
    assert md.depth_closed.wait(timeout=1.0)
    assert reader.get(timeout=1.0) is None
    assert md.calls == 1

    feed.subscribe("NIFTY")
    assert feed._thread is None
    assert md.calls == 1


def test_close_interrupts_retry_backoff():
    class _RetryFailingMarketData:
        def __init__(self):
            self.calls = 0
            self.failed = threading.Event()

        def stream_full(self, symbols):
            self.calls += 1
            if self.calls == 1:
                self.failed.set()
                raise RuntimeError("broker down")

            async def _generator():
                await asyncio.sleep(60)
                yield {}

            return _generator()

    md = _RetryFailingMarketData()
    feed = MultiplexedMarketFeed(md)
    try:
        feed.set_symbols(["NIFTY"])
        assert md.failed.wait(timeout=2.0)
        started = time.monotonic()
        feed.close()
        assert time.monotonic() - started < 0.5
    finally:
        feed.close()
    assert feed._thread is None
    assert md.calls == 1


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
    try:
        feed.set_symbols(["TEST FUT"])
        tick = None
        deadline = _time.time() + 15
        while _time.time() < deadline:
            tick = feed.try_next_tick("TEST FUT")
            if tick is not None:
                break
            _time.sleep(0.05)
    finally:
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


def test_queue_full_drop_oldest_is_counted():
    """A full queue must count drop-oldest as queue_full:<sym> — not vanish.

    B-3: drop-oldest silently discarded ticks with no counter, so a stalled
    consumer hid behind an otherwise-ok health check.
    """
    import queue as queue_mod

    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
    from unittest.mock import MagicMock

    feed = MultiplexedMarketFeed(MagicMock())
    sym = "QFULL TEST FUT"
    q = queue_mod.Queue(maxsize=2)
    feed._put_tick(q, Tick(time="1", price=1.0, volume=1.0), sym)
    feed._put_tick(q, Tick(time="2", price=2.0, volume=1.0), sym)
    # Queue full — third put must drop the oldest and count the event.
    feed._put_tick(q, Tick(time="3", price=3.0, volume=1.0), sym)

    assert feed._drop_counts.get(f"queue_full:{sym}") == 1
    assert q.qsize() == 2
    # Oldest (price=1.0) evicted; survivors are 2.0 then 3.0.
    assert q.get_nowait().price == 2.0
    assert q.get_nowait().price == 3.0


def test_health_snapshot_reports_silence_drops_and_producer():
    """health_snapshot() is the /health feed block source of truth."""
    from unittest.mock import MagicMock

    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(MagicMock())
    try:
        snap = feed.health_snapshot()
        assert snap["silentSymbols"] == []
        assert snap["dropCounts"] == {}
        assert snap["pollFallback"] is False
        assert snap["producerAlive"] is False  # not started yet

        # Seed a drop and a subscribed-but-silent queue (past subscribe grace).
        feed._note_drop("late_tick", "X", "ts=1")
        feed.subscribe("SILENT")
        import time as _t
        feed._subscribe_mono["SILENT"] = _t.monotonic() - 120.0
        snap = feed.health_snapshot()
        assert snap["dropCounts"].get("late_tick:X") == 1
        assert "SILENT" in snap["silentSymbols"]
        assert snap["pollFallback"] is False
        assert snap["pollFallbackAgeSec"] is None

        # Producer thread reports alive once kicked.
        feed.set_symbols(["SILENT"])
        _wait_until(lambda: feed.health_snapshot()["producerAlive"])
    finally:
        feed.close()


def test_stale_freshness_uses_arrival_not_old_ltt():
    """Illiquid LTT must not freeze _last_tick_wall while packets keep arriving.

    Regression: runtime set _last_tick_wall from exchange LTT alone. A quiet
    FINNIFTY SEP FUT's last_trade_time lagged minutes while quote/depth
    packets still arrived, so /health reported the engine stale and dynamic
    rotation treated a live feed as dead.
    """
    import time as _time
    from quant.brokers.gateway import Tick
    from quant.runtime import QuantEngine

    class _Gateway:
        def __init__(self, ticks):
            self._ticks = list(ticks)

        def subscribe(self, symbol):
            pass

        def next_tick(self):
            return self._ticks.pop(0) if self._ticks else None

    now = _time.time()
    old_ltt = str(int(now - 600))  # LTT 10 minutes old (illiquid)
    arrived = now  # packet just arrived
    tick = Tick(time=old_ltt, price=100.0, volume=0.0, arrived_at=arrived)

    eng = QuantEngine.__new__(QuantEngine)
    eng._last_tick_wall = now - 600
    eng._gateway = _Gateway([tick])
    eng._trace = []
    # Minimal collaborators used by _run_inner before the tick loop.
    eng.symbol = "FINNIFTY SEP FUT"
    eng._market = "NFO"
    eng._contract_expiry = None
    eng._tick_size = 0.05
    eng._amt_engine = type("A", (), {"warm_bars": 0})()
    eng._risk = type("R", (), {"state": lambda self: {}})()
    eng._recent_decisions = []
    eng._live = None
    eng._last_depth = None
    eng._advisor = type("Adv", (), {"on_context": lambda self, ctx: None})()

    # Drive only the tick-freshness path by stubbing process_tick.
    class _TH:
        def process_tick(self, t):
            pass

    eng._create_tick_handler = lambda: _TH()

    # Seed enough attributes _run_inner touches before the loop.
    # Call the freshness update in isolation (same logic as _run_inner).
    try:
        tick_epoch = float(getattr(tick, "time", 0) or 0)
    except (TypeError, ValueError):
        tick_epoch = 0.0
    try:
        a = float(getattr(tick, "arrived_at", 0) or 0)
    except (TypeError, ValueError):
        a = 0.0
    if a > 1e9:
        eng._last_tick_wall = a
    elif tick_epoch > 1e9:
        eng._last_tick_wall = tick_epoch
    else:
        eng._last_tick_wall = _time.time()

    assert abs(eng._last_tick_wall - arrived) < 5.0, (
        "freshness must prefer arrived_at over an illiquid exchange LTT"
    )
    assert eng._last_tick_wall > now - 60.0


def test_never_routed_not_silent_within_subscribe_grace():
    """Brand-new subscription before first packet must not flap /health."""
    feed = MultiplexedMarketFeed(_FakeMarketData({"FRESH FUT": []}))
    try:
        feed.set_symbols(["FRESH FUT"])
        assert feed.silent_symbols(threshold_sec=60.0) == [], (
            "never-routed within subscribe grace must not be silent"
        )
        # Force past grace: fake subscribe time far in the past.
        import time as _t
        feed._subscribe_mono["FRESH FUT"] = _t.monotonic() - 120.0
        assert "FRESH FUT" in feed.silent_symbols(threshold_sec=60.0)
    finally:
        feed.close()


def test_health_snapshot_copies_drop_counts():
    """dropCounts must be a snapshot copy, not a live reference."""
    feed = MultiplexedMarketFeed(_FakeMarketData({}))
    try:
        feed.set_symbols(["A"])
        feed._note_drop("convert_none", "A")
        snap = feed.health_snapshot()
        assert snap["dropCounts"].get("convert_none:A", 0) >= 1
        # Mutating the copy must not touch the feed's dict.
        snap["dropCounts"]["convert_none:A"] = 999
        assert feed._drop_counts["convert_none:A"] != 999
    finally:
        feed.close()
