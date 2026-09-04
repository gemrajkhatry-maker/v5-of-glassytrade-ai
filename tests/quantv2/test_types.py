from quantv2.types import Bar, Context, Signal, Decision

def test_types_hold_decision():
    b = Bar(time="2026-09-04T10:00:00+05:30", open=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)
    ctx = Context(symbol="X", bar=b, vah=None, val=None, poc=None, cvd_slope=0.0)
    d = Decision(approved=False, reason="NO_EDGE")
    assert d.reason == "NO_EDGE" and ctx.bar.close == 100.5


def test_context_tick_no_direction():
    b = Bar(time="t", open=1.0, high=1.0, low=1.0, close=1.0, delta=2.0)
    ctx = Context(symbol="X", bar=b, tick=0.05)
    assert ctx.tick == 0.05 and b.delta == 2.0 and not hasattr(ctx, "direction")
