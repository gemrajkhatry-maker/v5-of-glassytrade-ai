"""Unit tests for ATR-Dynamic Range Bar Generator (spec §4)."""

from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.range_bars import ATRRangeCalculator, DynamicRangeBarAggregator


def test_atr_range_calculator_updates_with_volatility():
    calc = ATRRangeCalculator(period=5, atr_multiplier=0.5, min_ticks=4, tick_size=0.05)
    assert calc.range_size >= 0.20  # min_ticks * tick_size = 4 * 0.05 = 0.20

    # Feed bars with increasing volatility (range 2.0 per bar)
    for i in range(5):
        bar = Bar(time=f"t{i}", open=100.0, high=102.0, low=100.0, close=101.5, volume=100)
        calc.update_bar(bar)

    # ATR should be ~2.0, so dynamic range = 0.5 * 2.0 = 1.0
    assert calc.range_size >= 0.90


def test_dynamic_range_bar_aggregator_emits_on_range_breach():
    agg = DynamicRangeBarAggregator(atr_period=5, atr_multiplier=0.5, min_ticks=4, tick_size=0.05)
    
    # Range is initially 0.20
    # Tick 1: price 100.0
    b1 = agg.add_tick(Tick(time="t0", price=100.0, volume=10))
    assert b1 is None

    # Tick 2: price 100.10 (spread 0.10 < 0.20)
    b2 = agg.add_tick(Tick(time="t1", price=100.10, volume=10))
    assert b2 is None

    # Tick 3: price 100.25 (spread 0.25 >= 0.20 -> bar closes!)
    b3 = agg.add_tick(Tick(time="t2", price=100.25, volume=10))
    assert b3 is not None
    assert b3.open == 100.0
    assert b3.high == 100.25
    assert b3.low == 100.0
    assert b3.close == 100.25
    assert b3.volume == 30
