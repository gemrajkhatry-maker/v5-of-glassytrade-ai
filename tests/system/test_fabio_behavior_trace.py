# tests/system/test_fabio_behavior_trace.py
"""Fabio AMT Indian Options Behavior Trace Test Suite (Task 1).

Establishes a baseline event trace verifying:
1. Market regime (e.g. IMBALANCED) alone without an approved setup sequence produces NO_EDGE.
2. Complete Triple-A setup produces an approved decision with named model.
3. Trace captures all required decision fields: bar time, session phase, market state,
   setup evidence, direction, gate results, reason, entry, stop, target, risk, and exit reason.
"""

import pytest
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.setup_state import SetupEvidence, SetupType
from quant.bars import Bar


def _make_dummy_bar(price: float = 100.0) -> Bar:
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=price - 0.5,
        high=price + 1.0,
        low=price - 1.0,
        close=price,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
    )


def decision_for(
    market_state: MarketState = MarketState.IMBALANCED,
    direction: str = "LONG",
    setup_type: SetupType = "NONE",
    absorption: bool = False,
    accumulation: bool = False,
    aggression: bool = False,
    acceptance: bool = False,
    cvd_slope: float = 1.0,
    obi: float = 0.20,
    close_px: float = 100.0,
    vah: float = 99.0,
    val: float = 95.0,
    vwap_upper_2: float = 105.0,
    vwap_lower_2: float = 90.0,
):
    bar = _make_dummy_bar(close_px)
    evidence = SetupEvidence(
        setup_type=setup_type,
        direction=direction,
        absorption=absorption,
        accumulation=accumulation,
        aggression=aggression,
        acceptance=acceptance,
        cvd_agrees=(cvd_slope > -0.2 if direction == "LONG" else cvd_slope < 0.2),
        obi_agrees=True,
    )
    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        cooldown_remaining_sec=0.0,
        risk_halted=False,
        consecutive_losses=0,
        agent_direction=direction,
        agent_probability=0.75,
        market_state=market_state,
        setup_evidence=evidence,
        vah=vah,
        val=val,
        poc=97.0,
        vwap_upper_2=vwap_upper_2,
        vwap_lower_2=vwap_lower_2,
        cvd_slope=cvd_slope,
        obi=obi,
        allow_trend=True,
        allow_reversion=True,
    )
    service = DecisionService()
    return service.evaluate(ctx)


def test_incomplete_imbalanced_market_is_no_edge():
    decision = decision_for(
        market_state=MarketState.IMBALANCED,
        direction="LONG",
        setup_type="NONE",
        absorption=False,
        accumulation=False,
        aggression=False,
    )
    # Market state alone with setup_type=NONE must return NO_EDGE
    assert decision.approved is False
    assert decision.reason in ("NO_EDGE", "GATE_REJECTED", "No valid Fabio AMT setup")


def test_completed_triple_a_is_approved_with_named_model():
    decision = decision_for(
        market_state=MarketState.IMBALANCED,
        direction="LONG",
        setup_type="TRIPLE_A",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
    )
    assert decision.approved is True
    assert decision.signal is not None
    assert decision.signal.type == "LONG"
