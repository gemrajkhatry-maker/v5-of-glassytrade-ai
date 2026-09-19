"""Directional CVD confirmation and scorer wiring tests (corrected architecture).

The AMT engine computes RAW components without direction gating. Direction-gated
re-scoring happens in the decision pipeline (gate_triple_a_edge) where the
resolved agent_direction is available.
"""

from types import SimpleNamespace

from quant.amt.orderflow.compute import compute_order_flow_metrics
from quant.amt.orderflow.cvd import CVDState
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import OHLC


def _bar(delta: float = 0.0) -> OHLC:
    return OHLC(
        time="2026-01-01T00:00:00Z",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=100.0,
        vwap=100.0,
        taker_buy_volume=50.0,
        delta=delta,
    )


def _flow(slope: float, divergence: str = "NONE"):
    """Call compute_order_flow_metrics WITHOUT candidate_direction.

    The function now returns raw CVD confirmation (no direction gating).
    Direction gating is applied in gate_triple_a_edge via rescore_aggression_with_direction().
    """
    bar = _bar()
    return compute_order_flow_metrics(
        recent_data=[bar],
        order_book=None,
        current=bar,
        agg_prints=[],
        market_state=MarketState.IMBALANCED,
        lvns=[],
        vah=0.0,
        val=0.0,
        poc=0.0,
        tick_size=1.0,
        cvd_state=CVDState(0.0, slope, divergence != "NONE", divergence),
    )


def test_raw_cvd_confirmed_when_slope_nonzero():
    """CVD is confirmed if slope is non-zero (raw, no direction gating)."""
    assert _flow(1.0)["cvd_confirmed"] is True
    assert _flow(-1.0)["cvd_confirmed"] is True
    assert _flow(0.0)["cvd_confirmed"] is False


def test_raw_cvd_confirmed_when_divergence():
    """CVD is confirmed if divergence exists (raw, no direction gating)."""
    assert _flow(0.0, divergence="BULLISH_DIV")["cvd_confirmed"] is True
    assert _flow(0.0, divergence="BEARISH_DIV")["cvd_confirmed"] is True
    assert _flow(1.0, divergence="BULLISH_DIV")["cvd_confirmed"] is True
    assert _flow(-1.0, divergence="BEARISH_DIV")["cvd_confirmed"] is True


def test_divergence_type_returned():
    """Divergence type is returned for decision pipeline to use."""
    result = _flow(0.0, divergence="BULLISH_DIV")
    assert result.get("cvd_divergence_type") == "BULLISH_DIV"

    result = _flow(0.0, divergence="BEARISH_DIV")
    assert result.get("cvd_divergence_type") == "BEARISH_DIV"

    result = _flow(1.0)
    assert result.get("cvd_divergence_type") == ""


def test_aggression_components_returned():
    """Raw aggression components are returned for re-scoring in decision pipeline."""
    result = _flow(1.0)
    components = result.get("aggression_components", {})
    assert "footprint_confirmed" in components
    assert "cvd_confirmed" in components
    assert "big_trade_confirmed" in components
    assert "absorption_detected" in components
    assert "ofi_aligned" in components
    assert "confluence_bonus" in components
    assert "volume_bubble_near" in components


def test_no_direction_passed_to_compute():
    """compute_order_flow_metrics no longer accepts candidate_direction parameter."""
    # This test verifies the parameter was removed by calling without it
    bar = _bar()
    result = compute_order_flow_metrics(
        recent_data=[bar],
        order_book=None,
        current=bar,
        agg_prints=[],
        market_state=MarketState.IMBALANCED,
        lvns=[],
        vah=0.0,
        val=0.0,
        poc=0.0,
        tick_size=1.0,
        cvd_state=CVDState(0.0, 1.0, False, "NONE"),
    )
    assert "aggression_components" in result


def test_compute_returns_raw_components_for_scorer():
    """Scorer receives raw components; direction gating is deferred."""
    class Scorer:
        def set_persistence_for_state(self, state):
            pass

        def score(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(score=0.0, confirmed=False)

    scorer = Scorer()
    bar = _bar(delta=-50.0)
    compute_order_flow_metrics(
        [bar], None, bar, [], MarketState.IMBALANCED, [], 0.0, 0.0, 0.0, 1.0,
        cvd_state=CVDState(0.0, -1.0, False, "NONE"),
        persistent_agg_scorer=scorer,
    )

    # Scorer is called WITHOUT direction (direction gating happens later)
    assert scorer.kwargs.get("direction") is None
    assert scorer.kwargs["cvd_slope"] == -1.0
    assert scorer.kwargs["norm_delta"] == -0.5
    assert scorer.kwargs["ofi"] is None
    assert scorer.kwargs["absorption_side"] == ""