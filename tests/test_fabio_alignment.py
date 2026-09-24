"""Tests for Fabio Valentini methodology alignment.

These tests validate that the implementation is aligned with Fabio's model:
  * 2-state market model (BALANCED / IMBALANCED) — no NO_TRADE/PROBING.
  * Triple-A aggression uses the current absorption cluster, VWAP, and CVD;
    LVN proximity is reserved for LVN-specific paths. Gate 3 does NOT know the
    market state, because the model router (BALANCED -> MEAN_REVERSION,
    IMBALANCED -> TREND; evidence may override) is enforced once in
    DecisionService (2026-09-17 decision D2).
  * The reversion (VA-fade) tier requires a failed probe reclaimed back inside
    the VA and targets the POC; it refuses dead markets.
  * Session phases cover the full trading day.
"""
import pytest

from quant.contracts.enums import MarketState, MarketStateCodec
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.gates_edge import gate_triple_a_edge
from quant.bars import Bar


# Test 1: MarketState is the Fabio 2-state model (BALANCED/IMBALANCED) plus
# exactly one volume-collapse veto (DEAD) that gates treat as "no edge".
# Fabio's auction model has two states; DEAD is not a third auction state —
# it is a data-quality veto emitted by analyzer._compute_effective_market_state
# when volume collapses, and both the Triple-A gate and the VA-fade fallback
# refuse to trade it. The legacy NO_TRADE/PROBING states must stay gone.
def test_market_state_is_two_state():
    states = list(MarketState)
    assert set(states) == {MarketState.BALANCED, MarketState.IMBALANCED, MarketState.DEAD}, (
        f"Unexpected state set: {states}"
    )

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
        triple_a_phase=kw.get("triple_a_phase", "AGGRESSION"),
        triple_a_signal=kw.get("triple_a_signal", kw.get("agent_direction", "LONG")),
        cvd_slope=kw.get("cvd_slope", 1.0),
        session_vwap=kw.get("session_vwap", 99.0),
        absorption_cluster_high=kw.get("absorption_cluster_high", 99.9),
        absorption_cluster_low=kw.get("absorption_cluster_low", 99.0),
        leg_lvn=kw.get("leg_lvn", 100.0),
        bid=kw.get("bid", close - 0.05),
        ask=kw.get("ask", close + 0.05),
    )


def test_triple_a_edge_does_not_require_lvn_proximity():
    at_lvn = gate_triple_a_edge(_ctx())
    assert at_lvn.passed

    away = gate_triple_a_edge(_ctx(leg_lvn=90.0))
    assert away.passed

    no_lvn = gate_triple_a_edge(_ctx(leg_lvn=0.0))
    assert no_lvn.passed


def test_dead_market_refused_by_gate3():
    dead = gate_triple_a_edge(_ctx(market_state="DEAD"))
    assert not dead.passed and "dead" in dead.reason.lower()


def test_balanced_market_does_not_approve_trend_edge_end_to_end():
    # D2: BALANCED selects MEAN_REVERSION, so a trend Triple-A edge is not
    # approved at the service level even though Gate 3 itself would pass.
    d = DecisionService().evaluate(_ctx(market_state="BALANCED"))
    assert not (d.approved and d.reason == "Triple-A")


def test_dead_market_no_trade():
    d = DecisionService().evaluate(_ctx(market_state="DEAD"))
    assert not d.approved and d.reason == "NO_EDGE"
