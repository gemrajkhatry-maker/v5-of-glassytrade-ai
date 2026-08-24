from quant.contracts.enums import SignalType
from quant.decision.decision_service import DecisionService, QuantDecision
from quant.decision.context import DecisionContext
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


def _state(triple_a_phase="", triple_a_signal=None):
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100.0, vah=100.5, val=99.5,
                                     step=0.1, total_volume=100),
        vwap=VWAPState(value=100.0, upper_1=101.0, lower_1=99.0,
                       upper_2=102.0, lower_2=98.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase=triple_a_phase, triple_a_signal=triple_a_signal,
    )


def _va_fade_state():
    return AuctionState(
        time="t", close=99.6,
        volume_profile=VolumeProfile(levels=(), poc=101.0, vah=102.0, val=100.0,
                                     step=0.5, total_volume=100),
        vwap=VWAPState(value=99.0, upper_1=100.0, lower_1=98.0,
                       upper_2=101.0, lower_2=97.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=50.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="BELOW_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def _thin_va_fade_state():
    # Same setup but step shrinks SL to 99.61 (0.01% stop, sub-0.1% -> rejected).
    return AuctionState(
        time="t", close=99.6,
        volume_profile=VolumeProfile(levels=(), poc=101.0, vah=102.0, val=100.0,
                                     step=0.39, total_volume=100),
        vwap=VWAPState(value=99.0, upper_1=100.0, lower_1=98.0,
                       upper_2=101.0, lower_2=97.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=50.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="BELOW_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def _quiet_state():
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100.0, vah=102.0, val=98.0,
                                     step=1.0, total_volume=100),
        vwap=VWAPState(value=100.0, upper_1=101.0, lower_1=99.0,
                       upper_2=102.0, lower_2=98.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def test_aggression_long_approved():
    ctx = DecisionContext(state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
                          bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == SignalType.BUY
    assert d.reason == "Triple-A"


def test_va_fade_fallback():
    ctx = DecisionContext(state=_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason == "VA_FADE"


def test_va_fade_thin_stop_rejected():
    # entry 99.6, SL at VAL - step = 99.61 -> ~0.01% stop -> rejected as NO_EDGE.
    ctx = DecisionContext(state=_thin_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_va_fade_healthy_stop_passes():
    # entry 99.6, SL at VAL - step = 99.5 -> ~0.1% stop -> guard met, fade passes.
    ctx = DecisionContext(state=_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason == "VA_FADE"


def test_no_edge():
    ctx = DecisionContext(state=_quiet_state(), bar=None, agent_direction=None, agent_probability=0.0)
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"


def test_no_state_guard():
    d = DecisionService().evaluate(DecisionContext(state=None, bar=None))
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"
    assert d.phase == "" and d.gate_results == ()
