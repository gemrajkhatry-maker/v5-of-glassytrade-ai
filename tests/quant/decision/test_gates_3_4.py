from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_direction_probability, gate_triple_a_edge
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.absorption import Absorption

def _ctx_imbalanced(**kw):
    """A gate-4 context with a real IMBALANCED market state (Fabio's
    out-of-balance requirement for the initiative edge)."""
    market_state = kw.pop("market_state", "IMBALANCED")
    agent_direction = kw.pop("agent_direction", "LONG")
    return DecisionContext(
        state=_state(**kw), bar=None,
        agent_direction=agent_direction,
        agent_probability=0.7,
        market_state=market_state,
    )


def _state(triple_a_phase="", triple_a_signal=None, close=100.0,
           cvd_slope=0.0, absorption=None, upper_1=101.0, lower_1=99.0):
    return AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=upper_1, lower_1=lower_1,
                       upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=cvd_slope,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=absorption,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase=triple_a_phase, triple_a_signal=triple_a_signal,
    )

def test_gate4_passes_with_direction_and_prob():
    r = gate_direction_probability(DecisionContext(state=_state(), bar=None,
        agent_direction="LONG", agent_probability=0.7))
    assert r.passed and r.gate == 4

def test_gate4_fails_flat():
    assert not gate_direction_probability(DecisionContext(state=_state(), bar=None,
        agent_direction="FLAT", agent_probability=0.7)).passed

def test_gate4_fails_low_probability():
    assert not gate_direction_probability(DecisionContext(state=_state(), bar=None,
        agent_direction="LONG", agent_probability=0.4)).passed

def test_gate4_cvd_conflict_blocks_long():
    r = gate_direction_probability(DecisionContext(state=_state(cvd_slope=-5),
        bar=None, agent_direction="LONG", agent_probability=0.7))
    assert not r.passed and "CVD" in r.reason

def test_gate5_passes_on_aggression_signal():
    r = gate_triple_a_edge(_ctx_imbalanced(triple_a_phase="AGGRESSION",
        triple_a_signal="LONG"))
    assert r.passed and r.gate == 5

def test_gate5_passes_on_fresh_absorption_breakout():
    r = gate_triple_a_edge(_ctx_imbalanced(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5))
    assert r.passed

def test_gate5_rejects_triple_a_direction_divergence():
    r = gate_triple_a_edge(_ctx_imbalanced(triple_a_phase="AGGRESSION",
        triple_a_signal="SHORT"))
    assert not r.passed
    assert "direction" in r.reason.lower()

def test_gate5_rejects_absorption_direction_conflict():
    r = gate_triple_a_edge(_ctx_imbalanced(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5,
        agent_direction="SHORT"))
    assert not r.passed
    assert "direction" in r.reason.lower()

def test_gate5_fails_no_edge():
    r = gate_triple_a_edge(_ctx_imbalanced())
    assert not r.passed and r.gate == 5

def test_gate5_stale_absorption_no_edge():
    r = gate_triple_a_edge(_ctx_imbalanced(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 10), upper_1=99.0, close=100.5))
    assert not r.passed

def test_gate5_rejects_balanced_market_even_with_edge():
    """Fabio: no initiative edge in balanced rotation. A valid AGGRESSION
    signal in a BALANCED market must be rejected by gate 5."""
    r = gate_triple_a_edge(_ctx_imbalanced(triple_a_phase="AGGRESSION",
        triple_a_signal="LONG", market_state="BALANCED"))
    assert not r.passed
    assert "balanced" in r.reason.lower()

def test_gate5_rejects_balanced_fresh_absorption_breakout():
    r = gate_triple_a_edge(_ctx_imbalanced(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5,
        market_state="BALANCED"))
    assert not r.passed
    assert "balanced" in r.reason.lower()

def test_gate5_rejects_dead_market():
    r = gate_triple_a_edge(_ctx_imbalanced(triple_a_phase="AGGRESSION",
        triple_a_signal="LONG", market_state="DEAD"))
    assert not r.passed
    assert "dead" in r.reason.lower()

def test_gate5_unknown_market_state_defaults_conservative():
    """Default DecisionContext.market_state is BALANCED — unknown state must
    never unlock an initiative entry."""
    r = gate_triple_a_edge(DecisionContext(state=_state(triple_a_phase="AGGRESSION",
        triple_a_signal="LONG"), bar=None, agent_direction="LONG"))
    assert not r.passed
    assert "balanced" in r.reason.lower()
