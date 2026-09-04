from quantv2.types import Bar, Context
from quantv2.setups import detect

def test_no_setup_flat_by_default():
    b = Bar(time="t", open=100.0, high=100.2, low=99.8, close=100.0, volume=1.0)
    ctx = Context(symbol="X", bar=b, cvd_slope=0.0, extra={})
    assert detect(ctx) is None

def test_lvn_uses_ctx_tick():
    b = Bar(time="t", open=100.0, high=100.2, low=99.8, close=100.0, volume=1.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, extra={"leg_lvn": 100.05, "absorption": "SELL_ABSORBED"})
    assert detect(ctx) == ("LVN_SNIPER", "LONG")
