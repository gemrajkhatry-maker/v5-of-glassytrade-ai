"""Production AMT engine direction handoff tests (corrected architecture)."""

from unittest.mock import patch

from quant.amt.orderflow.compute import compute_order_flow_metrics
from quant.amt.orderflow.cvd import CVDState
from quant.amt.orderflow.aggression import PersistentAggressionScorer
from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult, OHLC
from quant.session_levels import SessionLevelStore


def _bar(delta: float) -> Bar:
    return Bar(
        time="2026-01-01T09:20:00Z",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=100.0,
        buy_volume=75.0,
        delta=delta,
    )


def test_engine_passes_no_candidate_direction_to_analyzer():
    """AMTEngine.analyze() does not pass candidate_direction to analyzer.

    The AMT engine is purely analytical; direction gating happens in the
    decision pipeline where agent_direction is resolved.
    """
    engine = AMTEngine("NIFTY", "NSE", SessionLevelStore())
    bar = _bar(50.0)
    result = AMTResult(
        market_state=MarketState.IMBALANCED,
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        cvd_slope=1.0,
        aggression=0.0,
        cvd_source="underlying",
    )
    with patch.object(engine._amt_analyzer, "analyze", return_value=result) as analyze:
        dto = engine.analyze(bar)

    # candidate_direction parameter removed from analyzer call
    assert "candidate_direction" not in analyze.call_args.kwargs


def test_compute_returns_raw_cvd_confirmed_without_direction():
    """compute_order_flow_metrics returns raw CVD confirmation (no direction gating).

    CVD is confirmed if slope != 0 or has_divergence, regardless of direction.
    Direction gating is applied in gate_triple_a_edge via rescore_aggression_with_direction().
    """
    current = OHLC(
        time="2026-01-01T09:20:00Z", open=100.0, high=101.0,
        low=99.0, close=100.5, volume=100.0, vwap=100.0,
        taker_buy_volume=75.0, delta=50.0,
    )
    # Opposing CVD slope (-1.0) with LONG candidate direction
    # OLD behavior: cvd_confirmed=False, CVD component zeroed
    # NEW behavior: cvd_confirmed=True (raw), direction gating deferred
    flow = compute_order_flow_metrics(
        recent_data=[current],
        order_book=None,
        current=current,
        agg_prints=[], market_state=MarketState.IMBALANCED, lvns=[],
        vah=0.0, val=0.0, poc=0.0, tick_size=1.0,
        cvd_state=CVDState(0.0, -1.0, False, "NONE"),
        persistent_agg_scorer=PersistentAggressionScorer(),
    )

    # Raw CVD confirmation - slope != 0 so confirmed
    assert flow["cvd_confirmed"] is True
    # Scorer receives raw components without direction, so CVD gets full credit
    assert flow["agg_result"].breakdown["cvd"] == 1.0  # AGGRESSION_CVD = 1.0
    assert "aggression_components" in flow
    assert flow["aggression_components"]["cvd_confirmed"] is True


def test_engine_dto_contains_aggression_components_for_rescoring():
    """AMT DTO includes aggression_components for decision pipeline re-scoring."""
    engine = AMTEngine("NIFTY", "NSE", SessionLevelStore())
    bar = _bar(50.0)
    result = AMTResult(
        market_state=MarketState.IMBALANCED,
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        cvd_slope=1.0,
        aggression=0.0,
        cvd_source="underlying",
        aggression_components={
            "footprint_confirmed": True,
            "cvd_confirmed": True,
            "big_trade_confirmed": False,
            "absorption_detected": False,
            "ofi_aligned": False,
            "confluence_bonus": False,
            "volume_bubble_near": False,
        },
        cvd_state=CVDState(0.0, 1.0, False, "NONE"),
        ofi_result=None,
        norm_delta=0.5,
    )
    with patch.object(engine._amt_analyzer, "analyze", return_value=result) as analyze:
        dto = engine.analyze(bar)

    assert "aggressionComponents" in dto
    assert dto["aggressionComponents"]["cvd_confirmed"] is True
    assert "cvdState" in dto
    assert "ofiResult" in dto
    assert "normDelta" in dto