"""WS-REALISM guards: min-stop distance + max-size clamp in SignalBuilder."""

import pytest

from quant.auction_state import AuctionState
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import (
    MAX_POSITION_QUANTITY,
    MIN_STOP_DISTANCE_PCT,
    SignalBuilder,
    clamp_quantity,
    is_min_stop_met,
    is_stop_too_thin,
)
from quant.location import LocationState
from quant.order_flow import OrderFlowState
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState


def _ctx(close, val, step, nearest):
    state = AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(
            levels=(), poc=close, vah=val + 2 * step, val=val, step=step,
            total_volume=100),
        vwap=VWAPState(value=close, upper_1=close + 1, lower_1=close - 1,
                       upper_2=close + 2, lower_2=close - 2, std=1,
                       deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=close + 5, ib_low=close - 5,
                               ib_complete=True, zone="INSIDE_VA",
                               nearest_level=nearest, distance_to_level=0),
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
    )
    return DecisionContext(state=state, bar=None, symbol="SYM",
                           agent_direction="LONG", agent_probability=0.7)


def _pass_results():
    return [GateResult(i, True) for i in range(1, 6)]


def test_defaults_are_exported_constants():
    assert MIN_STOP_DISTANCE_PCT == 0.1
    assert MAX_POSITION_QUANTITY == 1000
    sb = SignalBuilder()
    assert sb.min_stop_distance_pct == MIN_STOP_DISTANCE_PCT
    assert sb.max_position_quantity == MAX_POSITION_QUANTITY


def test_thin_stop_setup_is_rejected():
    # entry 104.92, SL at VAL - 2 ticks = 104.819 (~0.096% away) -> rejected.
    sb = SignalBuilder()
    ctx = _ctx(close=104.92, val=104.919, step=0.01, nearest=104.9)
    assert sb.build(ctx, _pass_results()) is None


def test_thin_stop_pure_function():
    assert is_stop_too_thin(104.92, 104.90) is True
    assert is_stop_too_thin(100.0, 99.9) is True
    assert is_stop_too_thin(100.0, 99.89) is False


def test_healthy_setup_still_builds():
    # SL 2.1% away (100 -> 97.9) -> builds normally.
    sb = SignalBuilder()
    ctx = _ctx(close=100.0, val=98.0, step=1.0, nearest=98.0)
    s = sb.build(ctx, _pass_results())
    assert s is not None and s.type == "LONG"
    assert s.sl == pytest.approx(97.9)


def test_override_min_stop_allows_thin_stop():
    # Explicit override (min_stop_distance_pct=0) permits the thin stop.
    sb = SignalBuilder(min_stop_distance_pct=0.0)
    ctx = _ctx(close=104.92, val=104.919, step=0.01, nearest=104.9)
    assert sb.build(ctx, _pass_results()) is not None


def test_quantity_is_clamped_to_max():
    # equity 100k @ 1% risk, |entry-sl| = 0.02 -> 50k units -> clamped to 1000.
    sb = SignalBuilder()
    qty = sb.size(equity=100_000.0, entry=104.92, sl=104.90,
                  risk_per_trade_pct=0.01)
    assert qty == MAX_POSITION_QUANTITY
    assert clamp_quantity(50_000.0) == MAX_POSITION_QUANTITY


def test_healthy_quantity_unclamped():
    # |entry-sl| = 3 -> 100k*0.01/3 = 333 < 1000 -> untouched.
    sb = SignalBuilder()
    qty = sb.size(equity=100_000.0, entry=100.0, sl=97.0,
                  risk_per_trade_pct=0.01)
    assert qty == pytest.approx(100_000.0 * 0.01 / 3.0)


def test_max_quantity_override():
    sb = SignalBuilder(max_position_quantity=500)
    qty = sb.size(equity=100_000.0, entry=104.92, sl=104.90,
                  risk_per_trade_pct=0.01)
    assert qty == 500


def test_is_min_stop_met_defaults_match_constant():
    # Positive form of is_stop_too_thin with the same 0.1% default.
    assert is_min_stop_met(100.0, 99.89) is True
    assert is_min_stop_met(100.0, 97.0) is True
    assert is_min_stop_met(104.92, 104.90) is False
    assert is_min_stop_met(100.0, 99.9) is False


def test_is_min_stop_met_negates_is_stop_too_thin():
    assert is_min_stop_met(100.0, 99.9) is not is_stop_too_thin(100.0, 99.9)
    assert is_min_stop_met(100.0, 99.89) is not is_stop_too_thin(100.0, 99.89)


def test_is_min_stop_met_override():
    assert is_min_stop_met(104.92, 104.90, min_stop_distance_pct=0.0) is True


def test_clamp_quantity_defaults_match_constant():
    assert clamp_quantity(MAX_POSITION_QUANTITY + 1) == MAX_POSITION_QUANTITY
    assert clamp_quantity(MAX_POSITION_QUANTITY) == MAX_POSITION_QUANTITY
    assert clamp_quantity(1.0) == 1.0
    assert clamp_quantity(MAX_POSITION_QUANTITY + 1, max_quantity=0) == MAX_POSITION_QUANTITY + 1
