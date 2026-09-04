from quantv2.types import Bar, Context
from quantv2.pipeline import decide
from quantv2.oms import PaperOMS

def _ctx(**kw):
    b = Bar(time="t", open=100.0, high=100.2, low=99.8, close=100.0, volume=1.0)
    return Context(symbol="X", bar=b, extra=kw.get("extra", {}))

def test_flat_bar_rejects_with_reason():
    d = decide(_ctx(), session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=PaperOMS())
    assert d.approved is False and d.signal is None and d.reason == "NO_EDGE"

def test_submit_failure_rejects():
    class BadOMS:
        def submit(self, signal, qty):
            raise RuntimeError("broker down")
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3,
                  extra={"triple_phase": "AGGRESSION", "triple_signal": "LONG", "acceptance": True})
    d = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=BadOMS())
    assert d.approved is False and d.reason == "SUBMIT_FAILED"

def test_portfolio_cap_rejects():
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3,
                  extra={"triple_phase": "AGGRESSION", "triple_signal": "LONG", "acceptance": True})
    d = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=PaperOMS(), open_risk=999999.0, risk_cap=1000.0)
    assert d.approved is False and d.reason == "PORTFOLIO_CAP"

def test_none_submit_rejects():
    class NoneOMS:
        def submit(self, signal, qty):
            return None
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3,
                  extra={"triple_phase": "AGGRESSION", "triple_signal": "LONG", "acceptance": True})
    d = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=NoneOMS())
    assert d.approved is False and d.reason == "SUBMIT_FAILED"

def test_approved_carries_submitted_position():
    b = Bar(time="t", open=100.0, high=101.0, low=98.0, close=100.0, volume=5.0)
    ctx = Context(symbol="X", bar=b, tick=0.05, vah=101.0, val=99.0, poc=100.8, cvd_slope=0.3,
                  extra={"triple_phase": "AGGRESSION", "triple_signal": "LONG", "acceptance": True})
    d = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=PaperOMS())
    assert d.approved is True and d.position is not None and d.position.qty > 0 and d.position.entry == d.signal.entry
