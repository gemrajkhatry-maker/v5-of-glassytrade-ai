"""Unit tests for LiveGateway (live market-data broker gateway)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.infrastructure.adapters.live_gateway import LiveGateway
from quant.brokers.gateway import Tick


def _ts(sec: int) -> datetime:
    return datetime(2026, 8, 7, 10, 0, sec, tzinfo=timezone.utc)


class FakeDhan:
    def __init__(self, packets):
        self._packets = packets

    async def stream_full(self, symbols):
        for pkt in self._packets:
            yield pkt


def _make_packets():
    return [
        {"timestamp": _ts(1), "ltp": 100.0, "volume": 100, "ltq": 10,
         "total_buy_qty": 50, "total_sell_qty": 30},
        {"timestamp": _ts(2), "ltp": 101.5, "volume": 110, "ltq": 5,
         "total_buy_qty": 60, "total_sell_qty": 38},
        {"timestamp": _ts(3), "ltp": 102.0, "volume": 120, "ltq": 0,
         "total_buy_qty": 70, "total_sell_qty": 50},
        {"timestamp": _ts(4), "ltp": 103.0, "volume": 130, "ltq": 20,
         "total_buy_qty": 75, "total_sell_qty": 55},
    ]


def _wait_for(gateway, count: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while gateway._queue.qsize() < count and time.monotonic() < deadline:
        time.sleep(0.01)
    assert gateway._queue.qsize() >= count, "producer did not enqueue all packets"


def _drain(gateway, count: int):
    _wait_for(gateway, count)
    return [gateway.next_tick() for _ in range(count)]


def test_next_tick_converts_packets_to_ticks():
    fake = FakeDhan(_make_packets())
    gateway = LiveGateway(fake, "SYM")
    gateway.subscribe("SYM")
    try:
        t0, t1, t2, t3 = _drain(gateway, 4)
    finally:
        gateway.close()

    assert all(isinstance(t, Tick) for t in (t0, t1, t2, t3))

    assert t0.price == 100.0
    assert t1.price == 101.5
    assert t0.volume == 10.0
    assert t1.volume == 5.0
    assert t2.volume == 10.0
    assert t3.volume == 20.0

    assert t0.buy_volume == 0.0
    assert t0.sell_volume == 0.0
    assert t1.buy_volume == 10.0
    assert t1.sell_volume == 8.0
    assert t3.buy_volume == 5.0
    assert t3.sell_volume == 5.0


def test_time_is_int_parseable_epoch():
    gateway = LiveGateway(FakeDhan(_make_packets()), "SYM")
    gateway.subscribe("SYM")
    try:
        ticks = _drain(gateway, 4)
    finally:
        gateway.close()

    for i, tick in enumerate(ticks, start=1):
        assert int(tick.time) == int(_ts(i).timestamp())
        assert tick.time.isdigit()


def test_no_premature_none_while_stream_open():
    gateway = LiveGateway(FakeDhan(_make_packets()), "SYM")
    gateway.subscribe("SYM")
    try:
        _wait_for(gateway, 4)
        for _ in range(4):
            tick = gateway.next_tick()
            assert tick is not None
            assert int(tick.time) > 0
    finally:
        gateway.close()


def test_tick_carries_oi_and_depth():
    packets = [
        {"timestamp": _ts(1), "ltp": 100.0, "volume": 100, "ltq": 10,
         "total_buy_qty": 50, "total_sell_qty": 30, "oi": 12345,
         "depth_bids": [{"price": 99.5, "qty": 25}, {"price": 99.0, "qty": 10}],
         "depth_asks": [{"price": 100.5, "qty": 8}]},
    ]
    gateway = LiveGateway(FakeDhan(packets), "SYM")
    gateway.subscribe("SYM")
    try:
        tick = _drain(gateway, 1)[0]
    finally:
        gateway.close()

    assert tick.oi == 12345.0
    assert tick.depth["bids"][0] == [99.5, 25.0]
    assert tick.depth["bids"][1] == [99.0, 10.0]
    assert tick.depth["asks"][0] == [100.5, 8.0]


def test_tick_depth_none_when_packet_has_no_depth():
    gateway = LiveGateway(FakeDhan(_make_packets()), "SYM")
    gateway.subscribe("SYM")
    try:
        tick = _drain(gateway, 1)[0]
    finally:
        gateway.close()

    assert tick.oi == 0.0
    assert tick.depth is None
