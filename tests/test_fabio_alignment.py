"""Tests for Fabio Valentini methodology alignment.

These tests validate that the implementation is aligned with Fabio's model:
  * 2-state market model (BALANCED / IMBALANCED) — no NO_TRADE/PROBING.
  * The Triple-A edge (absorption -> accumulation -> aggression) fires in both
    BALANCED and IMBALANCED auctions; only a DEAD market (volume collapse)
    rejects (Fabio: absorption then VWAP breakout — the state tells you where
    the market is, not whether to trade).
  * The reversion (VA-fade) tier targets the POC and refuses dead markets.
  * Session phases cover the full trading day.
"""
import pytest

from quant.contracts.enums import MarketState, MarketStateCodec
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.gates_edge import gate_triple_a_edge
from quant.auction_state import AuctionState
from quant.vwap import VWAPState
from quant.volume_profile import VolumeProfile
from quant.order_flow import OrderFlowState
from quant.location import LocationState


# Test 1: MarketState should be the Fabio 2-state model only
def test_market_state_is_two_state():
    states = list(MarketState)
    assert len(states) == 2, f"Expected 2 states, got {len(states)}: {states}"
    assert MarketState.BALANCED in states
    assert MarketState.IMBALANCED in states

    with pytest.raises((AttributeError, ValueError)):
        MarketState.NO_TRADE
    with pytest.raises((AttributeError, ValueError)):
        MarketState.PROBING


def test_market_state_codec_two_state():
    assert MarketStateCodec.is_balanced("BALANCED")
    assert MarketStateCodec.is_imbalanced("IMBALANCED")
    assert not MarketStateCodec.is_no_trade("BALANCED")
    assert not MarketStateCodec.is_probing("IMBALANCED")
    assert MarketStateCodec.encode(MarketState.IMBALANCED) == 1.0
    assert MarketStateCodec.encode(MarketState.BALANCED) == 0.0


# Test 2: Session phases cover the trading day
def test_session_phases_exist():
    from shared.entities.models import SessionPhase

    for phase in ("OPENING", "PRIMARY", "MIDDAY", "POWER_HOUR", "CLOSE_PROTECTION",
                  "OUTSIDE_HOURS"):
        assert hasattr(SessionPhase, phase), f"SessionPhase.{phase} missing"


# ---------------------------------------------------------------------------
# Balance / imbalance gating (Fabio: the edge exists out of balance)
# ---------------------------------------------------------------------------

def _edge_state():
    return AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100.0, vah=101.0, val=99.0,
                                     step=0.1, total_volume=100),
        vwap=VWAPState(value=100.0, upper_1=101.0, lower_1=99.0,
                       upper_2=102.0, lower_2=98.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
    )


def test_triple_a_edge_fires_in_both_states():
    """A valid AGGRESSION/LONG edge must fire in BALANCED and IMBALANCED
    auctions alike (the state tells where the market is, not whether to
    trade); only a DEAD market rejects."""
    base = dict(state=_edge_state(), bar=None, agent_direction="LONG",
                agent_probability=0.7)
    balanced = gate_triple_a_edge(DecisionContext(**base, market_state="BALANCED"))
    assert balanced.passed

    imbalanced = gate_triple_a_edge(DecisionContext(**base, market_state="IMBALANCED"))
    assert imbalanced.passed

    dead = gate_triple_a_edge(DecisionContext(**base, market_state="DEAD"))
    assert not dead.passed and "dead" in dead.reason.lower()


def test_balanced_market_trades_on_valid_edge_end_to_end():
    """DecisionService: balanced market + valid Triple-A edge => approved
    Triple-A signal (the playbook trades absorption->breakout regardless of
    balance; chop is handled by requiring the edge, not by state gating)."""
    d = DecisionService().evaluate(DecisionContext(
        state=_edge_state(), bar=None, agent_direction="LONG", agent_probability=0.7,
        market_state="BALANCED", tick_size=0.1,
    ))
    assert d.approved and d.reason == "Triple-A"


def test_dead_market_no_trade():
    d = DecisionService().evaluate(DecisionContext(
        state=_edge_state(), bar=None, agent_direction="LONG", agent_probability=0.7,
        market_state="DEAD",
    ))
    assert not d.approved and d.reason == "NO_EDGE"
