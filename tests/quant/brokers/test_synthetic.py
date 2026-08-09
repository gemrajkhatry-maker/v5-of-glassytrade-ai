# tests/quant/brokers/test_synthetic.py
from quant.bars import Bar
from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway


def test_replays_ticks_in_order():
    ticks = [Tick(t, 100+i, 10, 6, 4) for i, t in enumerate(["t0", "t1", "t2"])]
    g = SyntheticGateway(ticks)
    g.subscribe("SYM")
    assert g.next_tick() == ticks[0]
    assert g.next_tick() == ticks[1]
    assert g.next_tick() == ticks[2]
    assert g.next_tick() is None
