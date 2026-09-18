"""Directional CVD confirmation and scorer wiring tests."""

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


def _flow(slope: float, direction: str):
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
        cvd_state=CVDState(0.0, slope, False, "NONE"),
        candidate_direction=direction,
    )


def test_imbalanced_cvd_only_confirms_matching_candidate_direction():
    assert _flow(1.0, "LONG")["cvd_confirmed"] is True
    assert _flow(-1.0, "SHORT")["cvd_confirmed"] is True


def test_imbalanced_cvd_does_not_confirm_opposing_candidate_direction():
    assert _flow(-1.0, "LONG")["cvd_confirmed"] is False
    assert _flow(1.0, "SHORT")["cvd_confirmed"] is False


def test_compute_forwards_signed_flow_to_directional_scorer():
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
        candidate_direction="LONG",
        persistent_agg_scorer=scorer,
    )

    assert scorer.kwargs["direction"] == "LONG"
    assert scorer.kwargs["cvd_slope"] == -1.0
    assert scorer.kwargs["norm_delta"] == -0.5
    assert scorer.kwargs["ofi"] is None
    assert scorer.kwargs["absorption_side"] == ""
