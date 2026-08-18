"""Gate 3 — TRIPLE_A_EDGE (Fabio: absorption -> accumulation -> aggression).

Simplified 2026-08-13: the edge exists in BOTH balanced and imbalanced
auctions (the playbook trades the same absorption/VWAP-breakout setup
everywhere); only a DEAD market rejects.
"""

from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState
from quant.absorption import Absorption


def _ctx(**kw):
    agent_direction = kw.pop("agent_direction", "LONG")
    market_state = kw.pop("market_state", "IMBALANCED")
    obi = kw.pop("obi", 0.0)
    return DecisionContext(
        state=_state(**kw), bar=None,
        agent_direction=agent_direction,
        agent_probability=0.7,
        market_state=market_state,
        obi=obi,
    )


def _state(triple_a_phase="", triple_a_signal=None, close=100.0,
           absorption=None, upper_1=101.0, lower_1=99.0):
    return AuctionState(
        time="t", close=close,
        volume_profile=VolumeProfile(levels=(), poc=100, vah=102, val=98, step=1, total_volume=100),
        vwap=VWAPState(value=100, upper_1=upper_1, lower_1=lower_1,
                       upper_2=102, lower_2=98, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0, cvd_slope=0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=absorption,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100, distance_to_level=0),
        triple_a_phase=triple_a_phase, triple_a_signal=triple_a_signal,
    )


def test_passes_on_aggression_signal():
    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION", triple_a_signal="LONG"))
    assert r.passed and r.gate == 3


def test_passes_on_fresh_absorption_breakout():
    r = gate_triple_a_edge(_ctx(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5))
    assert r.passed


def test_rejects_triple_a_direction_divergence():
    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION", triple_a_signal="SHORT"))
    assert not r.passed
    assert "direction" in r.reason.lower()


def test_rejects_absorption_direction_conflict():
    r = gate_triple_a_edge(_ctx(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5,
        agent_direction="SHORT"))
    assert not r.passed
    assert "direction" in r.reason.lower()


def test_fails_no_edge():
    r = gate_triple_a_edge(_ctx())
    assert not r.passed and r.gate == 3


def test_stale_absorption_no_edge():
    r = gate_triple_a_edge(_ctx(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 10), upper_1=99.0, close=100.5))
    assert not r.passed


def test_passes_in_balanced_market_with_edge():
    """Fabio playbook (simplified): the Triple-A edge is valid in balance too —
    same absorption/breakout rule, no imbalance-only restriction."""
    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION",
                                triple_a_signal="LONG", market_state="BALANCED"))
    assert r.passed


def test_passes_balanced_fresh_absorption_breakout():
    r = gate_triple_a_edge(_ctx(
        absorption=Absorption(0, 100, 500, "BUY", 0.5, 0), upper_1=99.0, close=100.5,
        market_state="BALANCED"))
    assert r.passed


def test_rejects_dead_market():
    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION",
                                triple_a_signal="LONG", market_state="DEAD"))
    assert not r.passed
    assert "dead" in r.reason.lower()


def test_passes_on_strong_bid_obi_breakout():
    """Depth reaches gate 3: a strong bid-side order book imbalance (OBI > 0)
    with price breaking beyond the upper VWAP band is the order-flow aggression
    leg of the Triple-A edge — no bar absorption required."""
    r = gate_triple_a_edge(_ctx(obi=0.65, upper_1=99.0, close=100.5))
    assert r.passed
    assert r.gate == 3


def test_passes_on_strong_ask_obi_breakout_short():
    """Ask-side imbalance (OBI < 0) below the lower VWAP band passes for SHORT."""
    r = gate_triple_a_edge(_ctx(
        agent_direction="SHORT", obi=-0.7, lower_1=101.0, close=99.5))
    assert r.passed


def test_rejects_obi_direction_conflict():
    """OBI pointing one way while the price is beyond the opposite VWAP band is
    not an aggression signal — the book and the move must agree."""
    r = gate_triple_a_edge(_ctx(obi=0.65, lower_1=101.0, close=99.5))
    assert not r.passed


def test_rejects_weak_obi_with_breakout():
    """A near-balanced book (|OBI| below the aggression threshold) is not enough
    on its own — the depth signal must be one-sided."""
    r = gate_triple_a_edge(_ctx(obi=0.15, upper_1=99.0, close=100.5))
    assert not r.passed
    assert "No Triple-A edge" in r.reason
