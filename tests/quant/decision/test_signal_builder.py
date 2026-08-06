import pytest
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import SignalBuilder
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.absorption import Absorption

def _ctx(**kw):
    state = AuctionState(
        time="t", close=kw.get("close", 100.0),
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=kw.get("absorption"),
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA",
                               nearest_level=100, distance_to_level=0),
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
    )
    return DecisionContext(state=state, bar=None, symbol="SYM",
                           agent_direction="LONG", agent_probability=0.7)

def _pass_results():
    return [GateResult(i, True) for i in range(1, 6)]

def test_build_returns_none_when_a_gate_fails():
    sb = SignalBuilder()
    results = _pass_results()
    results[2] = GateResult(3, False, "No direction")
    assert sb.build(_ctx(), results) is None

def test_build_returns_long_signal():
    sb = SignalBuilder()
    s = sb.build(_ctx(), _pass_results())
    assert s is not None and s.type == "LONG"
    assert s.sl < s.entry < s.tp
    assert s.rr >= 1.0

def test_build_tp_is_r_multiple():
    sb = SignalBuilder(tp_multiplier=2.0)
    s = sb.build(_ctx(), _pass_results())
    expected_tp = s.entry + (s.entry - s.sl) * 2.0
    assert s.tp == pytest.approx(expected_tp)

def test_confidence_from_absorption():
    sb = SignalBuilder()
    s = sb.build(_ctx(absorption=Absorption(0, 100, 500, "BUY", 0.8, 0)), _pass_results())
    assert s.confidence == pytest.approx(0.8)
