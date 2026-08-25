"""Tick -> Bar aggregator tests."""

from quant.brokers.gateway import Tick
from quant.aggregator import BarAggregator


def test_interval_bar_closes_on_boundary():
    a = BarAggregator(interval_seconds=60)
    assert a.add_tick(Tick("t0", 100.0, 10, 6, 4)) is None
    b = a.add_tick(Tick("t60", 101.0, 10, 6, 4))   # next minute boundary
    assert b is not None and b.close == 100.0 and b.high == 100.0 and b.low == 100.0
    assert b.volume == 10


def test_bar_aggregates_high_low_volume():
    a = BarAggregator(interval_seconds=60)
    a.add_tick(Tick("t0", 100.0, 10, 6, 4))
    a.add_tick(Tick("t1", 102.0, 5, 3, 2))
    a.add_tick(Tick("t2", 99.0, 7, 2, 5))
    b = a.add_tick(Tick("t60", 100.0, 1, 1, 0))
    assert b.high == 102.0 and b.low == 99.0 and b.volume == 22


def test_in_window_ticks_return_none():
    a = BarAggregator(interval_seconds=60)
    assert a.add_tick(Tick("t0", 100.0, 1, 1, 0)) is None
    assert a.add_tick(Tick("t1", 101.0, 1, 1, 0)) is None
    assert a.add_tick(Tick("t59", 99.0, 1, 1, 0)) is None


def test_bar_delta_is_buy_minus_sell():
    a = BarAggregator(interval_seconds=60)
    a.add_tick(Tick("t0", 100.0, 10, 6, 4))
    a.add_tick(Tick("t1", 102.0, 5, 3, 2))
    b = a.add_tick(Tick("t60", 100.0, 1, 1, 0))
    assert b.buy_volume == 9.0 and b.sell_volume == 6.0 and b.delta == 3.0


def test_open_close_accumulate():
    a = BarAggregator(interval_seconds=60)
    a.add_tick(Tick("t0", 100.0, 10, 6, 4))
    a.add_tick(Tick("t1", 102.0, 5, 3, 2))
    b = a.add_tick(Tick("t60", 101.0, 1, 1, 0))
    assert b.open == 100.0 and b.close == 102.0


def test_range_bar_closes_on_price_move():
    a = BarAggregator(range_size=5.0)
    assert a.add_tick(Tick("t0", 100.0, 1, 1, 0)) is None
    assert a.add_tick(Tick("t1", 102.0, 1, 1, 0)) is None
    b = a.add_tick(Tick("t2", 105.0, 1, 1, 0))     # high-low >= 5 closes
    assert b is not None and b.high == 105.0 and b.low == 100.0


def test_range_bar_uses_tick_time_not_window():
    a = BarAggregator(range_size=10.0)
    assert a.add_tick(Tick("t0", 100.0, 1, 1, 0)) is None
    b = a.add_tick(Tick("t60", 110.0, 1, 1, 0))
    assert b is not None and b.close == 110.0


def test_non_numeric_tick_time_falls_back_to_counter():
    a = BarAggregator(interval_seconds=60)
    assert a.add_tick(Tick("now", 100.0, 1, 1, 0)) is None
    b = a.add_tick(Tick("now", 101.0, 1, 1, 0))
    assert b is None   # same fallback window, no boundary crossed
