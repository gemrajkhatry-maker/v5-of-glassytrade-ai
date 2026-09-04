from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.coordinator import Coordinator


def test_eod_flattens():
    c = Coordinator(risk_cap=100000.0)
    c.add(Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0))
    c.on_tick("X", 0, 100.0, 1.0, 0.0)
    assert c.eod_flatten() == 0
