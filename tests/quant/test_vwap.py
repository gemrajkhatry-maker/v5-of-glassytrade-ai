from quant.bars import Bar
from quant.vwap import VWAPBuilder

def test_vwap_is_volume_weighted():
    vb = VWAPBuilder()
    # big volume at 100, tiny volume at 200 -> vwap close to 100
    vb.update(Bar(time="t1", open=100, high=100, low=100, close=100, volume=1000))
    vb.update(Bar(time="t2", open=200, high=200, low=200, close=200, volume=1))
    v = vb.snapshot()
    assert 100 <= v.value <= 101

def test_std_is_volume_weighted_not_simple():
    vb = VWAPBuilder()
    vb.update(Bar(time="t1", open=100, high=100, low=100, close=100, volume=1000))
    vb.update(Bar(time="t2", open=200, high=200, low=200, close=200, volume=1))
    v = vb.snapshot()
    # simple std of [100,200] would be 50; volume-weighted must be far smaller
    assert v.std < 10

def test_bands_monotonic():
    vb = VWAPBuilder()
    for i in range(20):
        vb.update(Bar(time=f"t{i}", open=100+i, high=100+i+1, low=100+i-1,
                      close=100+i, volume=100))
    v = vb.snapshot()
    assert v.lower_2 < v.lower_1 < v.value < v.upper_1 < v.upper_2
