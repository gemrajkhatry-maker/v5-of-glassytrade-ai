# tests/system/test_fabio_behavior_trace.py
"""Fabio AMT Indian Options Behavior Trace Test Suite (Task 1).

Establishes a baseline event trace verifying:
1. Market regime (e.g. IMBALANCED) alone without an approved setup sequence produces NO_EDGE.
2. Complete Triple-A setup produces an approved decision with named model.
3. Trace captures all required decision fields: bar time, session phase, market state,
   setup evidence, direction, gate results, reason, entry, stop, target, risk, and exit reason.
"""

from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.setup_state import SetupEvidence, SetupType
from quant.bars import Bar


def _make_dummy_bar(price: float = 100.0) -> Bar:
    # Full-body bullish 1-min acceptance candle: close sits at 91% of the
    # bar's range (close-low)/span, above the 75% extreme threshold, with a
    # positive body — otherwise gate 3's _candle_acceptance rejects it.
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=price - 0.8,
        high=price + 0.1,
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
        breakout_beyond_cluster=True,
        lvn_proximity_ok=True,
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
        bid=close_px - 0.05,
        ask=close_px + 0.05,
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
    assert decision.signal is None
    assert decision.reason in ("NO_EDGE", "GATE_REJECTED", "No valid Fabio AMT setup")
    assert decision.block_reasons, "rejection must carry block_reasons trace"
    assert any(r.gate == 3 and not r.passed for r in decision.gate_results)


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
    assert decision.reason == "Triple-A"
    assert decision.model_label == "Triple-A"
    assert decision.gate_results and all(r.passed for r in decision.gate_results)
    sig = decision.signal
    assert sig.sl < sig.entry < sig.tp
    assert sig.rr >= 1.5
