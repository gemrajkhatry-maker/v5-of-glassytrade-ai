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
        volume_profile=kw.get("volume_profile", VolumeProfile(
            levels=(), poc=100, vah=102, val=98, step=1, total_volume=100)),
        vwap=VWAPState(value=100, upper_1=101, lower_1=99, upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=kw.get("absorption"),
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA",
                               nearest_level=kw.get("nearest", 100), distance_to_level=0),
        triple_a_phase="AGGRESSION", triple_a_signal=kw.get("triple_a_signal", "LONG"),
    )
    return DecisionContext(state=state, bar=None, symbol="SYM",
                           agent_direction=kw.get("direction", "LONG"), agent_probability=0.7)

def _pass_results():
    return [GateResult(i, True) for i in range(1, 5)]

def test_build_returns_none_when_a_gate_fails():
    sb = SignalBuilder()
    results = _pass_results()
    results[3] = GateResult(4, False, "No direction")
    assert sb.build(_ctx(), results) is None

def test_build_returns_long_signal():
    sb = SignalBuilder()
    s = sb.build(_ctx(), _pass_results())
    assert s is not None and s.type == "LONG"
    # SL anchored two ticks (0.10) below VAL: val=98 -> 97.9 (Task 4 placement).
    assert s.sl == pytest.approx(98.0 - 0.10)
    assert s.sl < s.entry < s.tp
    assert s.rr >= 1.0

def test_build_tp_is_r_multiple():
    sb = SignalBuilder(tp_multiplier=2.0)
    s = sb.build(_ctx(), _pass_results())
    expected_tp = s.entry + (s.entry - s.sl) * 2.0
    assert s.tp == pytest.approx(expected_tp)

def test_model_label_populated():
    """Signal.model_label must be a non-empty string (replaces the removed confidence field)."""
    sb = SignalBuilder()
    s = sb.build(_ctx(), _pass_results(), model_label="Triple-A")
    assert s.model_label == "Triple-A"

def test_build_returns_none_when_sl_on_wrong_side_of_entry():
    sb = SignalBuilder()
    # entry 100 < val 110 so the anchor falls back to nearest_level=105;
    # SL = 105 - 0.10 = 104.90 lands above entry -> inverted -> rejected.
    ctx = _ctx(volume_profile=VolumeProfile(
        levels=(), poc=100, vah=102, val=110, step=1, total_volume=100),
        nearest=105)
    assert sb.build(ctx, _pass_results()) is None

def test_build_emits_short_with_sl_above_entry():
    sb = SignalBuilder()
    # SHORT: entry 100 < vah 102 -> SL = vah + 2 ticks = 102.10 (above entry),
    # TP below entry. The correct invariant is sl > entry > tp.
    ctx = _ctx(direction="SHORT", close=100.0, volume_profile=VolumeProfile(
        levels=(), poc=98, vah=102, val=99, step=1, total_volume=100),
        nearest=101)
    results = _pass_results()
    s = sb.build(ctx, results)
    assert s is not None and s.type == "SHORT"
    assert s.sl > s.entry > s.tp
    assert s.sl == pytest.approx(102.0 + 0.10)
