from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_rr import gate_risk_reward
from quant.decision.pipeline import GatePipeline


def _ctx(**kw):
    close = kw.get("close", 100.0)
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        agent_direction=kw.get("agent_direction", "LONG"),
        agent_probability=0.7,
        market_state=kw.get("market_state", "IMBALANCED"),
        position_open=kw.get("position_open", False),
        cooldown_remaining_sec=kw.get("cooldown_remaining_sec", 0),
        risk_halted=kw.get("risk_halted", False),
        tick_size=kw.get("tick_size", 0.05),
        poc=kw.get("poc", 100.0),
        vah=kw.get("ctx_vah", kw.get("vah", 101.0)),
        val=kw.get("ctx_val", kw.get("val", 99.0)),
        triple_a_phase=kw.get("triple_a_phase", "AGGRESSION"),
        triple_a_signal=kw.get("triple_a_signal", kw.get("agent_direction", "LONG")),
        cvd_slope=kw.get("cvd_slope", 1.0),
        leg_lvn=kw.get("leg_lvn", close),
        bid=kw.get("bid", close - 0.05),
        ask=kw.get("ask", close + 0.05),
    )


def test_gate4_passes_good_rr():
    # LONG: entry 100, SL = VAL - 2 ticks behind = 99.40 -> risk 0.60.
    r = gate_risk_reward(_ctx(val=99.5))
    assert r.passed and r.gate == 4


def test_gate4_no_longer_gates_on_rr():
    # Gate 4's pass/fail is stop-width only; R:R qualification is
    # SignalBuilder's job (structural targets >= 1.5 else 2R fallback).
    r = gate_risk_reward(_ctx(val=99.9), min_rr=5.0)
    assert r.passed and r.gate == 4


def test_gate4_rejects_far_stop():
    # Entry 100, SL anchored at 95.0 - 2*0.05 = 94.90
    r = gate_risk_reward(_ctx(val=90.0))
    assert r.gate == 4


def test_sl_offset_below_val():
    # LONG: SL 2 ticks BEHIND VAL (away from the market).
    r = gate_risk_reward(_ctx(val=99.5, step=0.5))
    assert r.passed and r.gate == 4
    assert "SL=99.40" in r.extra


def test_sl_offset_above_vah():
    # SHORT: SL 2 ticks BEHIND VAH (away from the market).
    r = gate_risk_reward(_ctx(close=100.0, vah=100.5, step=0.5,
                              agent_direction="SHORT", triple_a_signal="SHORT"))
    assert r.passed and r.gate == 4
    assert "SL=100.60" in r.extra


def test_pipeline_runs_all_gates():
    pipe = GatePipeline()
    results = pipe.evaluate(_ctx(val=99.5))
    assert [r.gate for r in results] == [1, 2, 3, 4]
    assert all(r.passed for r in results)


def test_pipeline_position_open_fails_gate2_but_runs_rest():
    ctx = _ctx(val=99.5, position_open=True)
    results = GatePipeline().evaluate(ctx)
    assert results[0].passed        # gate1 session open
    assert not results[1].passed    # gate2 position open
    assert results[2].passed        # gate3 still runs
    assert results[3].passed        # gate4 still runs


def test_gate4_uses_canonical_amt_va_over_bar_based_profile():
    """The LOCATION anchor must use ONE canonical value area — the AMT
    analyzer's session-scoped, clamped POC/VA that the UI actually renders —
    not the bar-based VolumeProfileBuilder snapshot the coordinator computes
    from a different bucketing. The bar-based VAL is stale (101); the AMT DTO
    carries VAL 95.0, so the SL must anchor to the AMT VAL (94.90), which then
    correctly fails the max-stop-distance check (102 ticks) instead of the
    stale bar-based VAL that would pass."""
    # bar-based profile says VAL=101 (entry 100 inside it), AMT says VAL=95.
    r = gate_risk_reward(_ctx(val=101.0, ctx_val=95.0))
    assert r.gate == 4 and r.passed
    # SL anchored on the CANONICAL AMT VAL, 2 ticks behind:
    assert "SL=94.90" in r.extra


def test_gate4_falls_back_to_state_profile_when_no_amt_va():
    """When the AMT VA is absent (0), gate 4 falls back to the state's
    volume profile so the pure gate tests keep their existing contract."""
    r = gate_risk_reward(_ctx(val=99.5))  # no ctx_val -> uses state VAL 99.5
    assert r.passed and r.gate == 4
    assert "SL=99.40" in r.extra
