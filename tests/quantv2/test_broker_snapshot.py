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
