from quantv2.types import Bar
from quantv2.oms import Position
from quantv2.exits import ExitConfig, evaluate_exit

def test_stop_then_trail():
    cfg = ExitConfig(time_stop_min=60, trail_ticks=4, tick=1.0)
    pos = Position(pid="p1", symbol="X", side="LONG", qty=10.0, entry=100.0, sl=99.0, tp=110.0, setup="T", opened_at="t")
    b1 = Bar(time="t1", open=100.0, high=106.0, low=100.0, close=105.0)
    d1, trail = evaluate_exit(pos, b1, {}, cfg)
    assert d1.should_exit is False and trail["peak"] == 106.0
    b2 = Bar(time="t2", open=105.0, high=105.0, low=101.0, close=103.0)
    d2, _ = evaluate_exit(pos, b2, trail, cfg)
    assert (d2.should_exit, d2.reason) == (True, "TRAIL")
