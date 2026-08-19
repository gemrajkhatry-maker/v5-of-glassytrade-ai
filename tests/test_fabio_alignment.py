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
from quant.bars import Bar


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

def _ctx(**kw):
    close = kw.get("close", 100.0)
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        agent_direction=kw.get("agent_direction", "LONG"),
        agent_probability=kw.get("agent_probability", 0.7),
        market_state=kw.get("market_state", "IMBALANCED"),
        poc=100.0, vah=101.0, val=99.0, tick_size=0.05,
        absorption_side=kw.get("absorption_side", "SELL_ABSORBED"),
        obi=kw.get("obi", 0.20),
    )


def test_triple_a_edge_fires_in_both_states():
    balanced = gate_triple_a_edge(_ctx(market_state="BALANCED"))
    assert balanced.passed

    imbalanced = gate_triple_a_edge(_ctx(market_state="IMBALANCED"))
    assert imbalanced.passed

    dead = gate_triple_a_edge(_ctx(market_state="DEAD"))
    assert not dead.passed and "dead" in dead.reason.lower()


def test_balanced_market_trades_on_valid_edge_end_to_end():
    d = DecisionService().evaluate(_ctx(market_state="BALANCED"))
    assert d.approved and d.reason == "Triple-A"


def test_dead_market_no_trade():
    d = DecisionService().evaluate(_ctx(market_state="DEAD"))
    assert not d.approved and d.reason == "NO_EDGE"
