"""Production AMT engine direction handoff tests."""

from unittest.mock import patch

from quant.amt.orderflow.compute import compute_order_flow_metrics
from quant.amt.orderflow.cvd import CVDState
from quant.amt.orderflow.aggression import PersistentAggressionScorer
from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult, OHLC
from quant.decision.context_builder import DecisionContextBuilder
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


def test_engine_handoff_keeps_long_context_and_rejects_opposing_flow():
    engine = AMTEngine("NIFTY", "NSE", SessionLevelStore())
    bar = _bar(50.0)
    scorer = PersistentAggressionScorer()
    opposing = compute_order_flow_metrics(
        recent_data=[OHLC(
            time=bar.time, open=bar.open, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume, vwap=100.0,
            taker_buy_volume=bar.buy_volume, delta=bar.delta,
        )],
        order_book=None,
        current=OHLC(
            time=bar.time, open=bar.open, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume, vwap=100.0,
            taker_buy_volume=bar.buy_volume, delta=bar.delta,
        ),
        agg_prints=[], market_state=MarketState.IMBALANCED, lvns=[],
        vah=0.0, val=0.0, poc=0.0, tick_size=1.0,
        cvd_state=CVDState(0.0, -1.0, False, "NONE"),
        persistent_agg_scorer=scorer,
        candidate_direction="LONG",
    )

    result = AMTResult(
        market_state=MarketState.IMBALANCED,
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        cvd_slope=1.0,
        aggression=opposing["aggression_score"],
        cvd_source="underlying",
    )
    with patch.object(engine._amt_analyzer, "analyze", return_value=result) as analyze:
        dto = engine.analyze(bar)

    assert analyze.call_args.kwargs["candidate_direction"] == "LONG"
    assert dto["aggression"] == 0.0
    assert DecisionContextBuilder()._resolve_direction(
        {**dto, "cvdSlope": 1.0, "ofi": 1.0},
        close_px=102.0, vah=101.0, val=99.0, obi=0.0, ofi=1.0,
        vwap_upper_1=101.0, vwap_lower_1=99.0,
    ) == "LONG"
