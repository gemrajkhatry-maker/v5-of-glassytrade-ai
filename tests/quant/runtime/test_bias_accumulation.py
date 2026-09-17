"""15-min bias aggregator accumulates bars from underlying ticks."""
from quant.bars import BIAS_INTERVAL_SEC
from quant.aggregator import BarAggregator
from quant.brokers.gateway import Tick


def test_bias_aggregator_accumulates_15min_bars():
    agg = BarAggregator(interval_seconds=BIAS_INTERVAL_SEC)
    # First tick opens the bar
    assert agg.add_tick(Tick("t0", 100.0, 10, 6, 4)) is None
    # In-window ticks return None
    assert agg.add_tick(Tick("t100", 101.0, 5, 3, 2)) is None
    assert agg.add_tick(Tick("t500", 99.0, 7, 2, 5)) is None
    # Crossing the 900s boundary closes the first bar
    closed = agg.add_tick(Tick("t900", 102.0, 1, 1, 0))
    assert closed is not None
    assert closed.open == 100.0
    assert closed.high == 101.0
    assert closed.low == 99.0
    assert closed.close == 99.0  # last tick in the window was t500 @ 99.0
    assert closed.volume == 22
