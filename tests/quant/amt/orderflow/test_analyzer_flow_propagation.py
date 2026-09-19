"""The active analyzer computes raw order-flow components (no direction gating)."""

from types import SimpleNamespace
from unittest.mock import patch

from quant.amt.orderflow.compute import compute_order_flow_metrics
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import OHLC


def _bar() -> OHLC:
    return OHLC(
        time="2026-01-01T00:00:00Z",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=100.0,
        vwap=100.0,
        taker_buy_volume=50.0,
        delta=0.0,
    )


def test_compute_returns_raw_components_without_direction():
    """compute_order_flow_metrics returns raw aggression components.

    No candidate_direction parameter. Direction-gated re-scoring happens in
    the decision pipeline (gate_triple_a_edge).
    """
    result = compute_order_flow_metrics(
        recent_data=[_bar()],
        order_book=None,
        current=_bar(),
        agg_prints=[],
        market_state=MarketState.IMBALANCED,
        lvns=[],
        vah=0.0,
        val=0.0,
        poc=0.0,
        tick_size=1.0,
        cvd_state=None,
    )

    # candidate_direction parameter removed
    # Returns raw components for re-scoring
    assert "aggression_components" in result
    components = result["aggression_components"]
    assert "footprint_confirmed" in components
    assert "cvd_confirmed" in components
    assert "big_trade_confirmed" in components
    assert "absorption_detected" in components
    assert "ofi_aligned" in components
    assert "confluence_bonus" in components
    assert "volume_bubble_near" in components

    # No direction-gated aggression score
    assert result["aggression_score"] == 0.0
    assert result["has_aggression"] is False
    assert result["agg_result"] is None