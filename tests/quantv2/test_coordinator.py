from quantv2.engine import Engine
from quantv2.oms import PaperOMS, Position
from quantv2.coordinator import Coordinator


def test_eod_flattens():
    c = Coordinator(risk_cap=100000.0)
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c.on_tick("X", 0, 100.0, 1.0, 0.0)
    assert c.eod_flatten() == 0


def test_headroom_and_eod_flatten():
    c = Coordinator(risk_cap=1000.0)
    a = Engine(symbol="A", interval_sec=60, oms=PaperOMS(), equity=100000.0)
    b = Engine(symbol="B", interval_sec=60, oms=PaperOMS(), equity=100000.0)
    c.add(a)
    c.add(b)
    a.position = Position(pid="p1", symbol="A", side="LONG", qty=10.0, entry=100.0, sl=99.0, tp=102.0, setup="T", opened_at="t")
    a.open_risk = 10.0
    assert c._headroom("B") == 990.0
    c.on_tick("A", 0, 101.0, 1.0, 0.0)
    assert c.eod_flatten() == 1
    assert a.position is None and a.open_risk == 0.0 and a.trail == {}
    assert c.eod_flatten() == 0
