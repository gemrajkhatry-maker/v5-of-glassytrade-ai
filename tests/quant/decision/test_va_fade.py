from quant.auction_state import AuctionState
from quant.decision.context import DecisionContext
from quant.decision.va_fade import detect_va_fade
from quant.location import LocationState
from quant.order_flow import OrderFlowState
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState


def _state(zone="INSIDE_VA", close=100.0, vwap=100.0, cvd=0.0,
           poc=100.0, vah=102.0, val=98.0, step=1.0):
    return AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(levels=(), poc=poc, vah=vah, val=val,
                                     step=step, total_volume=100),
        vwap=VWAPState(value=vwap, upper_1=vwap + 1, lower_1=vwap - 1,
                       upper_2=vwap + 2, lower_2=vwap - 2, std=1,
                       deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=cvd, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone=zone, nearest_level=0, distance_to_level=0),
        triple_a_phase="", triple_a_signal=None,
    )


def test_long_fade_below_val():
    state = _state(zone="BELOW_VA", close=99.6, vwap=99.0, cvd=50.0,
                   poc=101.0, val=100.0, step=0.5)
    sig = detect_va_fade(state)
    assert sig is not None
    assert sig.direction == "LONG"
    assert sig.tp == 101.0
    assert sig.sl == 99.5
    assert sig.entry == 99.6
    assert sig.rr > 0


def test_short_fade_above_vah():
    state = _state(zone="ABOVE_VA", close=100.5, vwap=101.0, cvd=-50.0,
                   poc=99.0, vah=100.0, step=0.5)
    sig = detect_va_fade(state)
    assert sig is not None
    assert sig.direction == "SHORT"
    assert sig.tp == 99.0
    assert sig.sl == 100.5
    assert sig.entry == 100.5


def test_no_fade_when_cvd_conflicts():
    state = _state(zone="BELOW_VA", close=99.6, vwap=99.0, cvd=-50.0,
                   poc=101.0, val=100.0, step=0.5)
    assert detect_va_fade(state) is None


def test_no_fade_inside_va():
    state = _state(zone="INSIDE_VA", close=99.6, vwap=99.0, cvd=50.0,
                   poc=101.0, val=100.0, step=0.5)
    assert detect_va_fade(state) is None


def test_no_fade_empty_profile():
    state = _state(zone="BELOW_VA", close=99.6, vwap=99.0, cvd=50.0,
                   poc=0.0, vah=0.0, val=0.0, step=0.0)
    assert detect_va_fade(state) is None


def test_context_param_optional():
    state = _state(zone="BELOW_VA", close=99.6, vwap=99.0, cvd=50.0,
                   poc=101.0, val=100.0, step=0.5)
    assert detect_va_fade(state, DecisionContext(state=state, bar=None)) is not None
