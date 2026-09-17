"""Structural anchor must never return a spread-noise (sub-0.1%) stop level.

Fabio: a stop inside ~0.1% of entry is noise. The old anchor returned the nearest
level even when its stop was unusable, so Gate 4 approved on a stop SignalBuilder
then dropped as "thin stop". The anchor now walks to the next structural level.
"""

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.signal_builder import SignalBuilder
from quant.decision.stops import min_stop_distance, structural_anchor, structural_stop


def _bar(close: float, low: float | None = None, high: float | None = None) -> Bar:
    return Bar(
        time="t", open=close, high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5, close=close, volume=100.0,
    )


def _ctx(**kw) -> DecisionContext:
    fields = dict(
        symbol="NIFTY", bar=_bar(kw.pop("close", 100.6), kw.pop("low", None),
                                 kw.pop("high", None)),
        agent_direction=kw.pop("agent_direction", "LONG"),
        tick_size=kw.pop("tick_size", 0.05),
        poc=kw.pop("poc", 100.0), vah=kw.pop("vah", 100.525),
        val=kw.pop("val", 99.0), leg_lvn=kw.pop("leg_lvn", 0.0),
        cvd_slope=kw.pop("cvd_slope", 1.0),
    )
    fields.update(kw)
    return DecisionContext(**fields)


def test_nearest_thin_level_is_skipped_for_a_deeper_one():
    # VAH at 100.525 is only 0.075 below entry -> thin; VAL at 99.0 is valid.
    ctx = _ctx(vah=100.525, val=99.0)
    anchor = structural_anchor(ctx, "LONG")
    assert anchor == 99.0
    sl = structural_stop("LONG", ctx.bar.close, anchor, ctx.tick_size)
    assert abs(ctx.bar.close - sl) >= min_stop_distance(ctx.bar.close, ctx.tick_size)


def test_all_thin_levels_fall_back_to_minimum_distance():
    # every structural level hugs entry -> stop placed at the noise floor
    ctx = _ctx(close=100.6, vah=100.58, val=100.55, low=100.57)
    anchor = structural_anchor(ctx, "LONG")
    sl = structural_stop("LONG", ctx.bar.close, anchor, ctx.tick_size)
    assert abs(ctx.bar.close - sl) >= min_stop_distance(ctx.bar.close, ctx.tick_size)


def test_healthy_nearest_level_is_unchanged():
    ctx = _ctx(close=100.6, val=98.0, vah=100.2, leg_lvn=100.0)
    assert structural_anchor(ctx, "LONG") == 100.0


def test_short_mirror_skips_a_thin_resistance():
    ctx = _ctx(close=100.0, agent_direction="SHORT", vah=100.075, val=101.0,
               high=100.2)
    anchor = structural_anchor(ctx, "SHORT")
    sl = structural_stop("SHORT", ctx.bar.close, anchor, ctx.tick_size)
    assert anchor > ctx.bar.close
    assert abs(sl - ctx.bar.close) >= min_stop_distance(ctx.bar.close, ctx.tick_size)


def test_signal_builder_emits_instead_of_dropping_thin_stop():
    # A certified breakout with a too-close VAH must still produce a tradeable
    # signal with a deeper structural stop, not be discarded as "thin stop".
    ctx = _ctx(close=100.6, vah=100.525, val=99.0, npoc_above=103.0)
    sig, why = SignalBuilder().build_or_reason(ctx, [], model_label="LVN_Sniper")
    assert sig is not None, f"unexpected drop: {why}"
    risk = abs(sig.entry - sig.sl)
    assert risk >= min_stop_distance(sig.entry, ctx.tick_size)
    assert sig.sl < sig.entry < sig.tp
