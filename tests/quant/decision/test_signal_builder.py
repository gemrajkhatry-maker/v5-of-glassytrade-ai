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
                           agent_direction=kw.get("direction", "LONG"), agent_probability=0.7,
                           prior_poc=kw.get("prior_poc", 0.0),
                           npoc_above=kw.get("npoc_above", 0.0),
                           npoc_below=kw.get("npoc_below", 0.0))

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
    # SL anchored two ticks (0.10) below VAL: val=98 -> 97.9 (Task 4 placement).
    assert s.sl == pytest.approx(98.0 - 0.10)
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

def test_build_returns_none_when_sl_on_wrong_side_of_entry():
    sb = SignalBuilder()
    # entry 100 < val 110 so the anchor falls back to nearest_level=105;
    # SL = 105 - 1 = 104 lands above entry -> inverted -> rejected.
    ctx = _ctx(volume_profile=VolumeProfile(
        levels=(), poc=100, vah=102, val=110, step=1, total_volume=100),
        nearest=105)
    assert sb.build(ctx, _pass_results()) is None

def test_build_emits_short_with_sl_above_entry():
    sb = SignalBuilder()
    # SHORT: entry 100 < vah 102 -> SL = vah + 2 ticks = 102.1 (above entry),
    # TP below entry. The correct invariant is sl > entry > tp.
    ctx = _ctx(direction="SHORT", close=100.0, volume_profile=VolumeProfile(
        levels=(), poc=98, vah=102, val=99, step=1, total_volume=100),
        nearest=101)
    results = _pass_results()
    s = sb.build(ctx, results)
    assert s is not None and s.type == "SHORT"
    assert s.sl > s.entry > s.tp
    assert s.sl == pytest.approx(102.0 + 0.10)


# ---------------------------------------------------------------------------
# Phase 1 — structural TP (Fabio: target the previous balance area / POC)
# Default geometry: entry 100, SL = val-2ticks = 97.9, risk 2.1, 2R TP = 104.2.
# ---------------------------------------------------------------------------

def test_build_long_tp_capped_at_nearest_npoc_above():
    sb = SignalBuilder()
    # npoc_above 104: capped rr = (104-100)/2.1 = 1.90 >= 1.5 -> cap applies.
    s = sb.build(_ctx(npoc_above=104.0), _pass_results())
    assert s is not None and s.tp == pytest.approx(104.0)
    assert s.rr == pytest.approx(4.0 / 2.1)

def test_build_long_tp_uses_nearest_of_npoc_and_prior_poc():
    sb = SignalBuilder()
    # prior_poc 103.9 is nearer than npoc_above 104.0 -> capped at 103.9.
    s = sb.build(_ctx(npoc_above=104.0, prior_poc=103.9), _pass_results())
    assert s.tp == pytest.approx(103.9)

def test_build_long_tp_uses_prior_poc_when_no_npoc():
    sb = SignalBuilder()
    s = sb.build(_ctx(prior_poc=104.0), _pass_results())
    assert s.tp == pytest.approx(104.0)

def test_build_long_tp_keeps_2r_when_capped_rr_below_min():
    sb = SignalBuilder()
    # npoc_above 103: capped rr = 1.0 < 1.5 -> cap rejected, 2R kept.
    s = sb.build(_ctx(npoc_above=103.0), _pass_results())
    assert s.tp == pytest.approx(s.entry + (s.entry - s.sl) * 2.0)

def test_build_long_tp_capped_when_min_rr_lowered():
    sb = SignalBuilder(min_rr=1.0)
    s = sb.build(_ctx(npoc_above=103.0), _pass_results())
    assert s.tp == pytest.approx(103.0)

def test_build_long_tp_keeps_2r_without_structure():
    sb = SignalBuilder()
    s = sb.build(_ctx(), _pass_results())
    assert s.tp == pytest.approx(s.entry + (s.entry - s.sl) * 2.0)

def test_build_short_tp_capped_at_nearest_npoc_below():
    sb = SignalBuilder()
    # SHORT: entry 100, SL = vah+2ticks = 102.1, risk 2.1, 2R TP = 95.8.
    # npoc_below 96: capped rr = (100-96)/2.1 = 1.90 >= 1.5 -> cap applies.
    ctx = _ctx(direction="SHORT", close=100.0, volume_profile=VolumeProfile(
        levels=(), poc=98, vah=102, val=99, step=1, total_volume=100), nearest=101,
        npoc_below=96.0)
    s = sb.build(ctx, _pass_results())
    assert s is not None and s.type == "SHORT"
    assert s.tp == pytest.approx(96.0)

def test_build_short_tp_keeps_2r_when_npoc_below_above_2r_target():
    sb = SignalBuilder()
    # npoc_below 98.5: capped rr = 0.71 < 1.5 -> rejected, 2R kept (95.8).
    ctx = _ctx(direction="SHORT", close=100.0, volume_profile=VolumeProfile(
        levels=(), poc=98, vah=102, val=99, step=1, total_volume=100), nearest=101,
        npoc_below=98.5)
    s = sb.build(ctx, _pass_results())
    assert s is not None and s.tp == pytest.approx(95.8)
