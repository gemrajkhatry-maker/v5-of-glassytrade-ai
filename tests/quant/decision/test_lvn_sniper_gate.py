"""Unit tests for Gate 3 Path C — Impulse Leg LVN Sniper (Playbook C per spec §9.3)."""

from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.absorption import Absorption


def _ctx(leg_lvn: float = 100.0, close: float = 100.0, absorption: Absorption | None = None, direction: str = "LONG") -> DecisionContext:
    state = AuctionState(
        time="t1", close=close,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=102, lower_1=98, upper_2=104, lower_2=96, std=2, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0.0, cvd_divergence="NONE", aggressive_prints=()),
        absorption=absorption,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True, zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase="WAITING",
        triple_a_signal=None,
    )
    return DecisionContext(
        state=state, bar=None, symbol="SYM",
        agent_direction=direction,
        agent_probability=0.8,
        market_state="BALANCED",
        session_open=True,
        warmup_complete=True,
        leg_lvn=leg_lvn,
        tick_size=0.05,
    )


def test_lvn_sniper_passes_on_retest_and_fresh_absorption():
    # Price is 100.05 (within 2 ticks of LVN 100.0) + fresh BUY absorption (bar_age=0)
    abs_buy = Absorption(
        bar_index=10, price=100.0, volume=500, side="BUY", strength=0.8, bar_age=0,
        cluster_high=100.2, cluster_low=99.8,
    )
    ctx = _ctx(leg_lvn=100.0, close=100.05, absorption=abs_buy, direction="LONG")
    result = gate_triple_a_edge(ctx)

    assert result.passed is True
    assert result.gate == 3
    assert "LVN Sniper LONG" in result.reason


def test_lvn_sniper_rejects_when_price_is_far_from_lvn():
    # Price is 102.0 (far from LVN 100.0)
    abs_buy = Absorption(
        bar_index=10, price=102.0, volume=500, side="BUY", strength=0.8, bar_age=0,
        cluster_high=102.2, cluster_low=101.8,
    )
    ctx = _ctx(leg_lvn=100.0, close=102.0, absorption=abs_buy, direction="LONG")
    result = gate_triple_a_edge(ctx)

    assert result.passed is False
    assert "No Triple-A edge" in result.reason


def test_lvn_sniper_rejects_stale_absorption():
    # Absorption is 2 bars old (bar_age=2) -> must reject
    abs_stale = Absorption(
        bar_index=8, price=100.0, volume=500, side="BUY", strength=0.8, bar_age=2,
        cluster_high=100.2, cluster_low=99.8,
    )
    ctx = _ctx(leg_lvn=100.0, close=100.0, absorption=abs_stale, direction="LONG")
    result = gate_triple_a_edge(ctx)

    assert result.passed is False
