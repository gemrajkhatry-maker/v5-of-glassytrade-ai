from unittest.mock import patch

import pytest

import quant.decision.signal_builder as sb_mod
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import SignalBuilder
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


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
    return [GateResult(i, True) for i in range(1, 6)]


def test_long_sl_sits_two_ticks_inside_val():
    sb = SignalBuilder()
    ctx = _ctx(close=110.0, volume_profile=VolumeProfile(
        levels=(), poc=100, vah=102, val=98, step=1, total_volume=100))
    s = sb.build(ctx, _pass_results())
    assert s is not None
    assert s.sl == pytest.approx(98.0 - 0.10, abs=1e-9)


def test_long_sl_falls_back_to_step_when_tick_math_fails():
    sb = SignalBuilder()
    ctx = _ctx(close=110.0, volume_profile=VolumeProfile(
        levels=(), poc=100, vah=102, val=98, step=1, total_volume=100))
    # Force the degenerate tick math path (sl >= anchor) to exercise
    # the step-based safety net.
    with patch.object(sb_mod, "TICK_SIZE_NSE_OPTIONS", 0.0):
        s = sb.build(ctx, _pass_results())
    assert s is not None
    assert s.sl == pytest.approx(98.0 - 1.0, abs=1e-9)


def test_short_sl_sits_two_ticks_above_vah():
    sb = SignalBuilder()
    ctx = _ctx(direction="SHORT", close=90.0, volume_profile=VolumeProfile(
        levels=(), poc=95, vah=102, val=98, step=1, total_volume=100))
    s = sb.build(ctx, _pass_results())
    assert s is not None
    assert s.sl == pytest.approx(102.0 + 0.10, abs=1e-9)


def test_sl_still_monotonic_with_signal_direction():
    sb = SignalBuilder()
    long_ctx = _ctx(close=110.0, volume_profile=VolumeProfile(
        levels=(), poc=100, vah=102, val=98, step=1, total_volume=100))
    short_ctx = _ctx(direction="SHORT", close=90.0, volume_profile=VolumeProfile(
        levels=(), poc=95, vah=102, val=98, step=1, total_volume=100))
    long_signal = sb.build(long_ctx, _pass_results())
    short_signal = sb.build(short_ctx, _pass_results())
    assert long_signal is not None
    assert short_signal is not None
    assert long_signal.sl < long_signal.entry < long_signal.tp
    assert short_signal.sl > short_signal.entry > short_signal.tp
