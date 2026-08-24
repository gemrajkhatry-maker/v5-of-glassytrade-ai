# tests/quant/test_absorption_test_warmup.py
# Regression tests for the absorption warm-up window and zero-division guard.
from quant.bars import Bar
from quant.absorption import AbsorptionDetector

def test_first_bar_does_not_crash():
    det = AbsorptionDetector()
    det.update(Bar(time="t0", open=100, high=100.2, low=99.8, close=100, volume=100))
    assert det.snapshot() is None

def test_no_absorption_during_warmup():
    det = AbsorptionDetector()
    for i in range(10):
        det.update(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    det.update(Bar(time="t10", open=100, high=100.2, low=99.8, close=100, volume=500))
    assert det.snapshot() is None

def test_warmup_boundary_first_min_bars_never_trigger():
    det = AbsorptionDetector()
    for i in range(19):
        det.update(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    det.update(Bar(time="t19", open=100, high=100.2, low=99.8, close=100, volume=500))
    assert det.snapshot() is None

def test_qualifies_after_warmup():
    det = AbsorptionDetector()
    for i in range(21):
        det.update(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    det.update(Bar(time="t21", open=100, high=100.2, low=99.8, close=100, volume=500))
    assert det.snapshot() is not None
