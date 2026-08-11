from quant.decision.context import DecisionContext
from quant.decision.gates_rr import gate_risk_reward
from quant.decision.pipeline import GatePipeline
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


def _ctx(**kw):
    state = AuctionState(
        time="t", close=kw.get("close", 100.0),
        volume_profile=VolumeProfile(levels=(), poc=100, vah=kw.get("vah", 101.0),
                                     val=kw.get("val", 99.0),
                                     step=kw.get("step", 0.05), total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA",
                               nearest_level=kw.get("nearest", 100), distance_to_level=0),
        triple_a_phase=kw.get("triple_a_phase", "AGGRESSION"),
        triple_a_signal=kw.get("triple_a_signal", "LONG"),
    )
    return DecisionContext(state=state, bar=None,
                           agent_direction=kw.get("agent_direction", "LONG"),
                           agent_probability=0.7,
                           market_state=kw.get("market_state", "IMBALANCED"),
                           position_open=kw.get("position_open", False),
                           cooldown_remaining_sec=kw.get("cooldown_remaining_sec", 0),
                           risk_halted=kw.get("risk_halted", False),
                           tick_size=kw.get("tick_size", 0.05))


def test_gate6_passes_good_rr():
    # LONG: entry 100, structural SL = val - step (support). val=99.5, step=0.05
    # -> SL 99.45 -> 0.55 risk, tp 101.1 -> rr 2.0, stop 11 ticks at 0.05.
    r = gate_risk_reward(_ctx(val=99.5))
    assert r.passed and r.gate == 6


def test_gate6_fails_poor_rr():
    # SL = val - step = 99.85 -> 0.15 away -> rr 2.0; force failure with high min_rr
    r = gate_risk_reward(_ctx(val=99.9), min_rr=5.0)
    assert not r.passed and r.gate == 6


def test_gate6_fails_stop_too_far():
    # SL = val - step = 94.95 -> 5.05 away = 101 ticks at 0.05 -> exceeds max
    r = gate_risk_reward(_ctx(val=95.0))
    assert not r.passed and r.gate == 6


def test_sl_offset_below_val():
    # LONG: SL anchored one step below VAL per amt_docs §2.6 (val - step).
    # val=99.5, step=0.5 -> SL 99.0, risk 1.0 = 20 ticks -> passes.
    r = gate_risk_reward(_ctx(val=99.5, step=0.5))
    assert r.passed and r.gate == 6
    assert "SL=99.00" in r.extra


def test_sl_offset_above_vah():
    # SHORT: SL anchored one step above VAH per amt_docs §2.6 (vah + step).
    # vah=100.5, step=0.5 -> SL 101.0, risk 1.0 = 20 ticks -> passes.
    r = gate_risk_reward(_ctx(close=100.0, vah=100.5, step=0.5,
                               agent_direction="SHORT", triple_a_signal="SHORT"))
    assert r.passed and r.gate == 6
    assert "SL=101.00" in r.extra


def test_pipeline_runs_all_gates():
    pipe = GatePipeline()
    results = pipe.evaluate(_ctx(val=99.5))
    assert [r.gate for r in results] == [1, 2, 3, 4, 5, 6, 7]
    assert all(r.passed for r in results)


def test_pipeline_gate7_disabled_passes_trivially():
    # Default ctx: llm_execution_enabled=False -> gate 7 passes (advisory-only).
    ctx = _ctx(val=99.5)
    results = GatePipeline().evaluate(ctx)
    g7 = results[6]
    assert g7.gate == 7 and g7.passed
    assert "advisory-only" in g7.reason


def test_pipeline_position_open_fails_gate2_but_runs_rest():
    ctx = _ctx(val=99.5, position_open=True)
    results = GatePipeline().evaluate(ctx)
    assert results[0].passed        # gate1 session open
    assert not results[1].passed    # gate2 position open
    assert results[2].passed        # gate3 still runs
