from quant.decision.va_fade import detect_va_fade
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _bar(o, h, l, c):
    return Bar(time=1, open=o, high=h, low=l, close=c, volume=1000,
               buy_volume=500, sell_volume=500, delta=0, oi=50000, vwap=(h+l+c)/3)


def _ctx(**kw):
    base = dict(symbol="TEST", poc=100.0, vah=102.0, val=98.0, tick_size=0.05)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def test_probe_below_val_reclaim_long_targets_poc():
    # low probed 96.5 (outside), close 98.6 back INSIDE VA, buyers in control
    ctx = _ctx(bar=_bar(98.8, 99.0, 96.5, 98.6), cvd_slope=0.7,
               session_extreme_low=96.5)
    sig = detect_va_fade(ctx)
    assert sig is not None and sig.direction == "LONG" and sig.tp == 100.0


def test_probe_above_vah_reclaim_short_targets_poc():
    ctx = _ctx(bar=_bar(101.2, 103.5, 101.0, 101.4), cvd_slope=-0.7,
               session_extreme_high=103.5)
    sig = detect_va_fade(ctx)
    assert sig is not None and sig.direction == "SHORT" and sig.tp == 100.0


def test_still_outside_va_is_not_a_fade():
    """Price below VAL and NOT reclaimed -> no fade (this is a trend, not a fade)."""
    ctx = _ctx(bar=_bar(97.5, 97.8, 96.0, 96.4), cvd_slope=0.7,
               session_extreme_low=96.0)
    assert detect_va_fade(ctx) is None


def test_reclaim_without_flow_agreement_is_not_a_fade():
    ctx = _ctx(bar=_bar(98.8, 99.0, 96.5, 98.6), cvd_slope=-0.7,
               session_extreme_low=96.5)
    assert detect_va_fade(ctx) is None


def test_stop_beyond_probe_extreme():
    ctx = _ctx(bar=_bar(98.8, 99.0, 96.5, 98.6), cvd_slope=0.7,
               session_extreme_low=96.5)
    sig = detect_va_fade(ctx)
    assert sig.sl < 96.5
