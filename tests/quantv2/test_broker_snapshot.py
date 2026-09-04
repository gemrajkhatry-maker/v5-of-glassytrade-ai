from quantv2.types import Signal
from quantv2.oms import PaperOMS
from quantv2.broker import BrokerAdapter, LiveNotEnabled
from quantv2.snapshot import snapshot
from quantv2.engine import Engine
from quantv2.coordinator import Coordinator
import pytest

def test_paper_live_guarded_and_snapshot():
    oms = PaperOMS()
    b = BrokerAdapter(mode="paper", oms=oms)
    sig = Signal(type="LONG", entry=100.0, sl=99.0, tp=102.0, rr=2.0, setup="T", symbol="X", timestamp="t")
    pos = b.submit(sig, 5)
    assert pos.qty == 5.0
    live = BrokerAdapter(mode="live", oms=oms, live_port=None)
    with pytest.raises(LiveNotEnabled):
        live.submit(sig, 5)
    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    snap = snapshot(c)
    assert snap["X"]["position"] is None

from quantv2.broker import BrokerAdapter
from quantv2.snapshot import snapshot

def test_live_port_delegates_and_last_decision_recorded():
    from quantv2.oms import PaperOMS
    from quantv2.engine import Engine
    from quantv2.coordinator import Coordinator
    from quantv2.types import Signal

    class FakePort:
        def __init__(self):
            self.calls = []
        def submit(self, signal, qty):
            self.calls.append((signal, qty))
            return ("live-order", signal, qty)

    port = FakePort()
    live = BrokerAdapter(mode="live", oms=PaperOMS(), live_port=port)
    sig = Signal(type="SHORT", entry=50.0, sl=51.0, tp=48.0, rr=2.0, setup="T", symbol="Y", timestamp="t")
    assert live.submit(sig, 3) == ("live-order", sig, 3)
    assert port.calls == [(sig, 3)]

    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    out = c.on_tick("X", 0, 100.0, 1.0, 0.0)
    assert out is None
    out = c.on_tick("X", 60, 100.0, 1.0, 0.0)
    assert out is not None and out.approved is False
    eng = c.engines["X"]
    assert eng.last_decision is out
    assert snapshot(c)["X"]["last_decision"] is out

def test_midbar_tick_keeps_last_decision():
    from quantv2.engine import Engine
    from quantv2.oms import PaperOMS
    from quantv2.coordinator import Coordinator
    c = Coordinator()
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c.on_tick("X", 0, 100.0, 1.0, 0.0)
    closed = c.on_tick("X", 60, 100.0, 1.0, 0.0)
    c.on_tick("X", 90, 100.1, 1.0, 0.0)
    assert c.engines["X"].last_decision is closed

def test_broker_port_contract():
    from quantv2.broker import BrokerPort
    from quantv2.oms import PaperOMS
    from quantv2.types import Signal
    class GoodPort:
        def submit(self, signal, qty):
            return PaperOMS().submit(signal, qty)
    port: BrokerPort = GoodPort()
    sig = Signal(type="LONG", entry=1.0, sl=0.9, tp=1.2, rr=2.0, setup="T", symbol="X", timestamp="t")
    assert port.submit(sig, 1).qty == 1.0
