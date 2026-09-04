from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.exits import ExitConfig


def test_engine_holds_then_exits():
    eng = Engine(symbol="X", interval_sec=60, oms=PaperOMS(), equity=100000.0, exit_cfg=ExitConfig(tick=0.05))
    d = eng.on_tick(0, 100.0, 1.0, 0.0)
    assert d is None
    d = eng.on_tick(60, 100.0, 1.0, 0.0)
    assert d is not None and d.approved is False and d.reason in ("NO_EDGE", "HOLDING")
