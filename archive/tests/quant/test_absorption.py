# tests/quant/test_absorption.py
from quant.bars import Bar
from quant.absorption import AbsorptionDetector

def _low_volume_bars(n=25):
    return [Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100)
            for i in range(n)]

def test_detects_buy_absorption():
    det = AbsorptionDetector()
    for b in _low_volume_bars():
        det.update(b)
    det.update(Bar(time="t25", open=100, high=100.2, low=99.8, close=100,
                   volume=500, buy_volume=450, sell_volume=50))  # vol 5x, tight range
    a = det.snapshot()
    assert a is not None and a.side == "BUY"

def test_wide_range_is_not_absorption():
    det = AbsorptionDetector()
    for b in _low_volume_bars():
        det.update(b)
    det.update(Bar(time="t25", open=100, high=110, low=90, close=100, volume=500))  # wide range
    assert det.snapshot() is None

def test_strength_bounded_and_age_tracks():
    det = AbsorptionDetector()
    for b in _low_volume_bars():
        det.update(b)
    det.update(Bar(time="t25", open=100, high=100.2, low=99.8, close=100, volume=800))
    a = det.snapshot()
    assert 0 <= a.strength <= 1
    det.update(Bar(time="t26", open=100, high=101, low=99, close=100, volume=100))
    assert det.snapshot().bar_age == 1
