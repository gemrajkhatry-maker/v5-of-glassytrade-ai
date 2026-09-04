from quantv2.dhan_feed import DhanFeed
from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS


class FakeTransport:
    def __init__(self, frames):
        self._frames = list(frames)

    def frames(self):
        return iter(self._frames)


def test_feed_routes_ticks():
    c = Coordinator()
    c.add(Engine(symbol="NF", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    feed = DhanFeed(c, {"NF": 1333}, FakeTransport([
        {"security_id": 1333, "ltp": 100.0, "volume": 1.0},
        {"security_id": 1333, "ltp": 100.5, "volume": 2.0},
    ]))
    n = feed.run_once()
    assert n == 2 and c.engines["NF"]._bucket is not None


def test_handle_frame_delta_tick_rule():
    c = Coordinator()
    c.add(Engine(symbol="NF", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    feed = DhanFeed(c, {"NF": 1333}, FakeTransport([]))
    assert feed.handle_frame({"security_id": 1333, "ltp": 100.0, "volume": 1.0}) == 1
    assert feed.handle_frame({"security_id": 1333, "ltp": 100.5, "volume": 2.0}) == 1
    assert feed.handle_frame({"security_id": 1333, "ltp": 99.5, "volume": 3.0}) == 1
    ticks = c.engines["NF"]._ticks
    assert [t[3] for t in ticks] == [0.0, 2.0, -3.0]


def test_handle_frame_by_symbol_when_no_security_id():
    c = Coordinator()
    c.add(Engine(symbol="NF", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    feed = DhanFeed(c, {"NF": 1333}, FakeTransport([]))
    assert feed.handle_frame({"symbol": "NF", "ltp": 100.0, "volume": 1.0}) == 1
    assert c.engines["NF"]._ticks[-1][1] == 100.0


def test_handle_frame_skips_unknown_and_invalid():
    c = Coordinator()
    c.add(Engine(symbol="NF", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    feed = DhanFeed(c, {"NF": 1333}, FakeTransport([]))
    assert feed.handle_frame({"security_id": 9999, "ltp": 100.0, "volume": 1.0}) == 0
    assert feed.handle_frame({"symbol": "ZZ", "ltp": 100.0, "volume": 1.0}) == 0
    assert feed.handle_frame({"security_id": 1333, "ltp": 0.0, "volume": 1.0}) == 0
    assert feed.handle_frame({}) == 0
    assert c.engines["NF"]._ticks == []


def test_by_id_inverted():
    c = Coordinator()
    feed = DhanFeed(c, {"NF": 1333, "BN": 402}, FakeTransport([]))
    assert feed.by_id_inverted() == {"NF": 1333, "BN": 402}
    assert feed.by_id == {1333: "NF", 402: "BN"}