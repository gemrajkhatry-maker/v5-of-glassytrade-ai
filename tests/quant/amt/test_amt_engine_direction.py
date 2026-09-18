"""Production AMT engine direction handoff tests."""

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


def test_engine_passes_closed_bar_direction_to_amt_analyzer():
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

    assert analyze.call_args.kwargs["candidate_direction"] == "LONG"


def test_compute_and_scorer_do_not_credit_opposing_cvd_for_long():
    current = OHLC(
        time="2026-01-01T09:20:00Z", open=100.0, high=101.0,
        low=99.0, close=100.5, volume=100.0, vwap=100.0,
        taker_buy_volume=75.0, delta=50.0,
    )
    flow = compute_order_flow_metrics(
        recent_data=[current],
        order_book=None,
        current=current,
        agg_prints=[], market_state=MarketState.IMBALANCED, lvns=[],
        vah=0.0, val=0.0, poc=0.0, tick_size=1.0,
        cvd_state=CVDState(0.0, -1.0, False, "NONE"),
        persistent_agg_scorer=PersistentAggressionScorer(),
        candidate_direction="LONG",
    )

    assert flow["cvd_confirmed"] is False
    assert flow["agg_result"].breakdown["cvd"] == 0.0
    assert flow["aggression_score"] == 0.0
