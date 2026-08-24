# tests/quant/test_bars.py
from quant.bars import Bar

def test_bar_defaults():
    b = Bar(time="t", open=1, high=2, low=0.5, close=1.5, volume=100)
    assert b.buy_volume == 0.0 and b.sell_volume == 0.0 and b.delta == 0.0
    assert b.high > b.low
