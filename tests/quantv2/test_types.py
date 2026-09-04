from quantv2.types import Bar, Context, Signal, Decision

def test_types_hold_decision():
    b = Bar(time="2026-09-04T10:00:00+05:30", open=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)
    ctx = Context(symbol="X", bar=b, direction=None, vah=None, val=None, poc=None, cvd_slope=0.0)
    d = Decision(approved=False, reason="NO_EDGE")
    assert d.reason == "NO_EDGE" and ctx.bar.close == 100.5
