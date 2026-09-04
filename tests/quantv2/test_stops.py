from quantv2.types import Bar, Context
from quantv2.stops import build_signal, StopTooWide
import pytest

def test_long_signal_monotonic_rr():
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3)
    sig = build_signal(ctx, "LONG", "TRIPLE_A")
    assert sig is not None and sig.sl < sig.entry < sig.tp and sig.rr >= 1.5

def test_wide_stop_raises_short_path_ok():
    b = Bar(time="t", open=100.0, high=100.1, low=99.9, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=120.0, val=80.0, poc=99.0)
    with pytest.raises(StopTooWide):
        build_signal(ctx, "LONG", "TRIPLE_A")
    bs = Bar(time="t", open=100.0, high=101.0, low=99.0, close=100.0, volume=5.0)
    sctx = Context(symbol="X", bar=bs, tick=0.05, vah=101.0, val=99.0, poc=99.0)
    sig = build_signal(sctx, "SHORT", "VA_FADE")
    assert sig is not None and sig.sl > sig.entry > sig.tp and sig.rr >= 1.5
