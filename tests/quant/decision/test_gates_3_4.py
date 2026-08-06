from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_direction_probability, gate_triple_a_edge
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.absorption import Absorption

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

def test_gate3_passes_with_direction_and_prob():
    r = gate_direction_probability(DecisionContext(state=_state(), bar=None,
        agent_direction="LONG", agent_probability=0.7))
    assert r.passed and r.gate == 3

def test_gate3_fails_flat():
    assert not gate_direction_probability(DecisionContext(state=_state(), bar=None,
        agent_direction="FLAT", agent_probability=0.7)).passed

def test_gate3_fails_low_probability():
    assert not gate_direction_probability(DecisionContext(state=_state(), bar=None,
        agent_direction="LONG", agent_probability=0.4)).passed

def test_gate3_cvd_conflict_blocks_long():
    r = gate_direction_probability(DecisionContext(state=_state(cvd_slope=-5),
        bar=None, agent_direction="LONG", agent_probability=0.7))
    assert not r.passed and "CVD" in r.reason

def test_gate4_passes_on_aggression_signal():
    r = gate_triple_a_edge(DecisionContext(state=_state(triple_a_phase="AGGRESSION",
        triple_a_signal="LONG"), bar=None))
    assert r.passed and r.gate == 4

def test_gate4_passes_on_fresh_absorption_breakout():
    r = gate_triple_a_edge(DecisionContext(state=_state(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5),
        bar=None))
    assert r.passed

def test_gate4_fails_no_edge():
    r = gate_triple_a_edge(DecisionContext(state=_state(), bar=None))
    assert not r.passed and r.gate == 4

def test_gate4_stale_absorption_no_edge():
    r = gate_triple_a_edge(DecisionContext(state=_state(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 10), upper_1=99.0, close=100.5),
        bar=None))
    assert not r.passed
