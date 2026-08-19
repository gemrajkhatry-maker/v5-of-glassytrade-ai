from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.va_fade import detect_va_fade


def _ctx(close=100.0, cvd=0.0, poc=100.0, vah=102.0, val=98.0, step=0.5):
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        poc=poc, vah=vah, val=val, tick_size=step, cvd_slope=cvd,
    )


def test_long_fade_below_val():
    ctx = _ctx(close=99.6, cvd=50.0, poc=101.0, val=100.0, step=0.5)
    sig = detect_va_fade(ctx)
    assert sig is not None
    assert sig.direction == "LONG"
    assert sig.tp == 101.0
    assert sig.sl == 99.1
    assert sig.entry == 99.6
    assert sig.rr > 0


def test_short_fade_above_vah():
    ctx = _ctx(close=100.5, cvd=-50.0, poc=99.0, vah=100.0, step=0.5)
    sig = detect_va_fade(ctx)
    assert sig is not None
    assert sig.direction == "SHORT"
    assert sig.tp == 99.0
    assert sig.sl == 101.0
    assert sig.entry == 100.5
    assert sig.rr == 3.0


def test_no_fade_when_cvd_conflicts():
    ctx = _ctx(close=99.6, cvd=-50.0, poc=101.0, val=100.0, step=0.5)
    assert detect_va_fade(ctx) is None


def test_no_fade_inside_va():
    ctx = _ctx(close=99.6, cvd=50.0, poc=101.0, vah=102.0, val=98.0, step=0.5)
    assert detect_va_fade(ctx) is None


def test_no_fade_on_missing_levels():
    ctx = _ctx(close=99.6, cvd=50.0, poc=0.0, vah=102.0, val=98.0, step=0.5)
    assert detect_va_fade(ctx) is None



