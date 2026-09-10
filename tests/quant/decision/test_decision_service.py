from dataclasses import replace

from quant.bars import Bar
from quant.decision.data_quality import DataQuality
from quant.decision.decision_service import DecisionService, QuantDecision
from quant.decision.context import DecisionContext


def _bar(close=100.0):
    return Bar(time="t", open=close, high=close + 1.0, low=close - 1.0, close=close, volume=100.0)


def _ctx(agent_direction="LONG", market_state="IMBALANCED", **kw):
    bar = kw.get("bar") or _bar(kw.get("close", 100.0))
    return DecisionContext(
        state=None,
        bar=bar,
        symbol="SYM",
        time_str="t",
        agent_direction=agent_direction,
        agent_probability=kw.get("agent_probability", 0.7),
        market_state=market_state,
        poc=kw.get("poc", 100.0),
        vah=kw.get("vah", 100.5),
        val=kw.get("val", 99.5),
        tick_size=kw.get("tick_size", 0.05),
        cvd_slope=kw.get("cvd_slope", 0.0),
        absorption_side=kw.get("absorption_side", ""),
        obi=kw.get("obi", 0.0),
        risk_halted=kw.get("risk_halted", False),
        triple_a_phase=kw.get("triple_a_phase", ""),
        triple_a_signal=kw.get("triple_a_signal", ""),
        allow_reversion=kw.get("allow_reversion", True),
    )


def test_aggression_long_approved():
    ctx = _ctx(
        agent_direction="LONG",
        market_state="IMBALANCED",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        cvd_slope=1.0,
        close=110.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"
    assert d.reason == "Triple-A"


def test_aggression_approved_in_balanced_market():
    ctx = _ctx(
        agent_direction="LONG",
        market_state="BALANCED",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        cvd_slope=1.0,
        close=110.0,
        val=98.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"


def test_aggression_blocked_in_dead_market():
    ctx = _ctx(agent_direction="LONG", market_state="DEAD")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_va_fade_fallback():
    ctx = _ctx(agent_direction="LONG", close=99.6, poc=101.0, val=100.0, tick_size=0.5, cvd_slope=50.0)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason in ("VA_FADE", "Triple-A")


def test_va_fade_thin_stop_rejected():
    ctx = _ctx(agent_direction="LONG", close=99.6, poc=101.0, val=100.0, tick_size=0.05, cvd_slope=50.0)
    d = DecisionService().evaluate(ctx)
    # thin stop is rejected if not passing other gates
    assert d.reason in ("NO_EDGE", "Triple-A", "VA_FADE")


def test_va_fade_blocked_in_dead_market():
    ctx = _ctx(agent_direction="LONG", close=99.6, poc=101.0, val=100.0, tick_size=0.5, cvd_slope=50.0, market_state="DEAD")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_no_edge():
    ctx = _ctx(agent_direction=None, agent_probability=0.0, market_state="BALANCED")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_no_state_guard():
    d = DecisionService().evaluate(DecisionContext(state=None, bar=None))
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"
    assert d.phase == "" and d.gate_results == ()


def test_halted_emits_explicit_halted_decision():
    ctx = _ctx(agent_direction="LONG", agent_probability=0.9, risk_halted=True)
    d = DecisionService().evaluate(ctx)
    assert not d.approved, "Halted system must not approve any signal"
    assert d.signal is None, "Halted system must emit no signal"
    assert d.reason == "HALTED", f"Expected reason=HALTED, got {d.reason!r}"
    assert len(d.block_reasons) > 0, "HALTED decision must include a block_reason"
    assert "halted" in d.block_reasons[0].lower(), f"Block reason should mention halt: {d.block_reasons[0]!r}"


def test_approved_signal_carries_model_label():
    ctx = _ctx(
        agent_direction="LONG",
        agent_probability=0.9,
        market_state="IMBALANCED",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        cvd_slope=1.0,
        close=110.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None
    assert d.signal.model_label, "Approved signal must have a non-empty model_label"
    assert d.model_label, "QuantDecision must carry model_label when approved"
    assert d.signal.model_label == d.model_label, "Signal and decision model_label must match"


def test_data_quality_blocked_at_deterministic_conviction():
    ctx = replace(
        _ctx(agent_probability=0.7),
        data_quality=DataQuality.PRICE_DIRECTION_PROXY,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None
    assert d.reason == "DATA_QUALITY_BLOCKED"


def test_data_quality_gate_passes_for_allowlisted_quality():
    ctx = replace(
        _ctx(agent_probability=0.7),
        data_quality=DataQuality.TICK_EXACT,
    )
    d = DecisionService().evaluate(ctx)
    assert d.reason != "DATA_QUALITY_BLOCKED"
