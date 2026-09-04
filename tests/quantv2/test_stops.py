from quantv2.types import Bar, Context
from quantv2.stops import build_signal

def test_long_signal_monotonic_rr():
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3)
    sig = build_signal(ctx, "LONG", "TRIPLE_A", tick=0.05)
    assert sig is not None and sig.sl < sig.entry < sig.tp and sig.rr >= 1.5
