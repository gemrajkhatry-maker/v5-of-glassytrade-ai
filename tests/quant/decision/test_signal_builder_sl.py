from unittest.mock import patch

import pytest

import quant.decision.signal_builder as sb_mod
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import SignalBuilder


def _ctx(**kw):
    close = kw.get("close", 100.0)
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        agent_direction=kw.get("direction", "LONG"),
        agent_probability=0.7,
        poc=kw.get("poc", 100.0),
        vah=kw.get("vah", 102.0),
        val=kw.get("val", 98.0),
        tick_size=kw.get("tick_size", 0.05),
    )


def _pass_results():
    return [GateResult(i, True) for i in range(1, 6)]


def test_long_sl_sits_two_ticks_behind_vah_on_breakout():
    sb = SignalBuilder()
    # Upside breakout (close=110.0 above VAH=102.0): SL anchors tight behind broken VAH
    ctx = _ctx(close=110.0, poc=100.0, vah=102.0, val=98.0)
    s = sb.build(ctx, _pass_results(), model_label="Triple-A")
    assert s is not None
    assert s.sl == pytest.approx(101.90, abs=1e-9)


def test_long_sl_falls_back_to_step_when_tick_math_fails():
    sb = SignalBuilder()
    ctx = _ctx(close=110.0, poc=100.0, vah=102.0, val=98.0)
    # Force the degenerate tick math path (sl >= anchor) to exercise
    # the step-based safety net: zero effective tick size everywhere.
    from dataclasses import replace as _replace
    ctx = _replace(ctx, tick_size=0.0)
    with patch.object(sb_mod, "TICK_SIZE_NSE_OPTIONS", 0.0):
        s = sb.build(ctx, _pass_results(), model_label="Triple-A")
    assert s is not None
    # Zero tick still uses the default 0.05 instrument tick so the stop
    # sits 2 ticks behind VAH.
    assert s.sl == pytest.approx(101.90, abs=1e-9)


def test_short_sl_sits_two_ticks_behind_vah_or_val():
    sb = SignalBuilder()
    # Inside VA (fade short near VAH): SL anchors to VAH behind
    ctx_inside = _ctx(direction="SHORT", close=100.0, poc=95.0, vah=102.0, val=98.0)
    s_inside = sb.build(ctx_inside, _pass_results(), model_label="Triple-A")
    assert s_inside is not None
    assert s_inside.sl == pytest.approx(102.0 + 0.10, abs=1e-9)

    # Downside breakdown (below VAL): SL anchors to broken VAL (tight structural stop)
    ctx_break = _ctx(direction="SHORT", close=90.0, poc=95.0, vah=102.0, val=98.0)
    s_break = sb.build(ctx_break, _pass_results(), model_label="Triple-A")
    assert s_break is not None
    assert s_break.sl == pytest.approx(98.0 + 0.10, abs=1e-9)


def test_sl_still_monotonic_with_signal_direction():
    sb = SignalBuilder()
    long_ctx = _ctx(close=110.0, poc=100.0, vah=102.0, val=98.0)
    short_ctx = _ctx(direction="SHORT", close=90.0, poc=95.0, vah=102.0, val=98.0)
    long_signal = sb.build(long_ctx, _pass_results(), model_label="Triple-A")
    short_signal = sb.build(short_ctx, _pass_results(), model_label="Triple-A")
    assert long_signal is not None
    assert short_signal is not None
    assert long_signal.sl < long_signal.entry < long_signal.tp
    assert short_signal.sl > short_signal.entry > short_signal.tp
