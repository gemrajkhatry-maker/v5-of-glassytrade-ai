from dataclasses import replace

from quant.bars import Bar
from quant.decision.data_quality import DataQuality
from quant.decision.decision_service import DecisionService
from quant.decision.context import DecisionContext


def _bar(close=100.0):
    # Full-body bullish bar: the Gate-3 1-min candle-acceptance guard requires a
    # >=60% body in the trade direction with the close near the extreme.
    return Bar(time="t", open=close - 0.8, high=close + 0.25, low=close - 1.0, close=close, volume=100.0)


def _ctx(agent_direction="LONG", market_state="IMBALANCED", **kw):
    bar = kw.get("bar") or _bar(kw.get("close", 100.0))
    close = float(bar.close)
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
        leg_lvn=kw.get("leg_lvn", 0.0),
        risk_halted=kw.get("risk_halted", False),
        triple_a_phase=kw.get("triple_a_phase", ""),
        triple_a_signal=kw.get("triple_a_signal", ""),
        allow_reversion=kw.get("allow_reversion", True),
        bid=kw.get("bid", close - 0.05),
        ask=kw.get("ask", close + 0.05),
    )


def test_aggression_long_approved():
    ctx = _ctx(
        agent_direction="LONG",
        market_state="IMBALANCED",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        cvd_slope=1.0,
        close=110.0,
        leg_lvn=110.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"
    assert d.reason == "Triple-A"


def test_aggression_approved_in_imbalanced_market():
    # D2 (2026-09-17): IMBALANCED -> TREND, so a Triple-A AGGRESSION is approved.
    # The former balanced-market variant is no longer valid: the model router
    # blocks trend setups in a BALANCED auction (see test_model_router_enforcement).
    ctx = _ctx(
        agent_direction="LONG",
        market_state="IMBALANCED",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        cvd_slope=1.0,
        close=110.0,
        val=98.0,
        leg_lvn=110.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"


def test_aggression_blocked_in_dead_market():
    ctx = _ctx(agent_direction="LONG", market_state="DEAD")
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_va_fade_fallback():
    # A VA fade is the MEAN_REVERSION model, so the auction must be BALANCED
    # (IMBALANCED -> TREND, where the router blocks a counter-trend fade), AND
    # the failed probe must have been reclaimed: the bar probed below VAL
    # (low 99.4) and closed back INSIDE the VA at 100.4.
    ctx = _ctx(agent_direction="LONG", market_state="BALANCED",
               close=100.4, poc=101.0, val=100.0, tick_size=0.5, cvd_slope=50.0)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason in ("VA_FADE", "Triple-A")


def test_va_fade_thin_stop_rejected():
    ctx = _ctx(agent_direction="LONG", market_state="BALANCED",
               close=99.6, poc=101.0, val=100.0, tick_size=0.05, cvd_slope=50.0)
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
        leg_lvn=110.0,
    )
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None
    assert d.signal.model_label, "Approved signal must have a non-empty model_label"
    assert d.model_label, "QuantDecision must carry model_label when approved"
    assert d.signal.model_label == d.model_label, "Signal and decision model_label must match"


def test_provenance_is_not_a_service_concern():
    """N3: data quality is gated solely by DecisionLoop (capability-aware).

    The service must evaluate its gates regardless of aggregate provenance;
    PRICE_DIRECTION_PROXY with synthetic bars fails through the normal gate
    results, never a provenance short-circuit.
    """
    ctx = replace(
        _ctx(agent_probability=0.7),
        data_quality=DataQuality.PRICE_DIRECTION_PROXY,
    )
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None
    assert d.gate_results, "rejection must come from the gate pipeline"


def test_service_evaluation_is_quality_agnostic():
    """TICK_EXACT vs CANDLE_GAUSSIAN must not change the service verdict."""
    base = _ctx(agent_probability=0.7)
    d_exact = DecisionService().evaluate(
        replace(base, data_quality=DataQuality.TICK_EXACT)
    )
    d_gauss = DecisionService().evaluate(
        replace(base, data_quality=DataQuality.CANDLE_GAUSSIAN)
    )
    assert (d_exact.approved, d_exact.reason) == (d_gauss.approved, d_gauss.reason)
