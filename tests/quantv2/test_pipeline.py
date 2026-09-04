from quantv2.types import Bar, Context
from quantv2.pipeline import decide

def test_flat_bar_rejects_with_reason():
    b = Bar(time="t", open=100.0, high=100.2, low=99.8, close=100.0, volume=1.0)
    ctx = Context(symbol="X", bar=b, extra={})
    d = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0)
    assert d.approved is False and d.signal is None and d.reason == "NO_EDGE"
