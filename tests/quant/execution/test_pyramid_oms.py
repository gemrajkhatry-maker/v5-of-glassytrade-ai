"""Unit tests for Pyramiding OMS & Multi-Tier Partial Exits (spec §13.2, §13.3)."""

import pytest

from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Position
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


def _make_signal(entry: float = 100.0, sl: float = 95.0, tp: float = 110.0, direction: str = "LONG") -> Signal:
    return Signal(
        type=direction,
        reason="Test",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=abs(tp - entry) / abs(entry - sl),
        model_label="Triple-A",
        symbol="SYM",
        timestamp="2026-08-18T10:00:00+05:30",
    )


def test_add_pyramid_creates_linked_position():
    oms = PaperOMS(lot_size=25.0)
    sig = _make_signal(entry=100.0, sl=95.0, tp=115.0)
    base_pos = oms.submit(sig, quantity=50.0)

    assert base_pos.pyramid_level == 0
    assert base_pos.is_pyramid is False
    assert base_pos.size == 50.0

    # Add Pyramid 1 at LVN 105.0 with SL at 102.0
    pyr1 = oms.add_pyramid(
        base=base_pos,
        entry_price=105.0,
        new_sl=102.0,
        size=25.0,  # 50% of base size
        time="2026-08-18T10:05:00+05:30",
        pyramid_level=1,
    )

    assert pyr1.pyramid_level == 1
    assert pyr1.is_pyramid is True
    assert pyr1.size == 25.0
    assert pyr1.open_price == 105.0
    assert pyr1.order.signal.sl == 102.0
    assert pyr1.order.signal.tp == 115.0  # inherits base TP


def test_close_partial_returns_fill_and_reduced_position():
    oms = PaperOMS(lot_size=10.0)
    sig = _make_signal(entry=100.0, sl=95.0, tp=110.0)
    pos = oms.submit(sig, quantity=100.0)

    # Close 50% at TP1 (110.0)
    fill, remaining = oms.close_partial(
        position=pos,
        fraction=0.50,
        price=110.0,
        time="2026-08-18T10:10:00+05:30",
        reason="TP1_50PCT",
    )

    assert fill.close_price == 110.0
    assert fill.pnl == (110.0 - 100.0) * 50.0 == 500.0
    assert fill.reason == "TP1_50PCT"
    assert remaining.size == 50.0
    assert remaining.open_price == 100.0


def test_is_risk_free_at_08r_profit():
    """Spec §13.1: Instant risk-zero triggers at +0.8R advance."""
    exits = ExitEngine()
    sig = _make_signal(entry=100.0, sl=90.0, tp=120.0)  # risk = 10.0
    oms = PaperOMS()
    pos = oms.submit(sig, 10.0)

    assert exits.is_risk_free(pos) is False

    state = AuctionState(
        time="t1", close=105.0,  # 0.5R profit -> not yet risk-free
        volume_profile=VolumeProfile(levels=(), poc=100, vah=105, val=95, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=102, lower_1=98, upper_2=104, lower_2=96, std=2, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0.0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="WAITING",
        triple_a_signal=None,
    )
    exits.evaluate(pos, state, bar_index=1, bar_high=105.0, bar_low=100.0)
    assert exits.is_risk_free(pos) is False

    # Price advances to 108.0 (+0.8R = +8.0)
    state_08r = AuctionState(
        time="t2", close=108.0,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=105, val=95, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=102, lower_1=98, upper_2=104, lower_2=96, std=2, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0.0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="WAITING",
        triple_a_signal=None,
    )
    exits.evaluate(pos, state_08r, bar_index=2, bar_high=108.5, bar_low=104.0)
    assert exits.is_risk_free(pos) is True
