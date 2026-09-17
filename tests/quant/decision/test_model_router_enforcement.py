"""DecisionService blocks a setup whose model disagrees with the active model."""
from unittest.mock import patch
from quant.contracts.enums import MarketState
from quant.decision.decision_service import DecisionService
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.bars import Bar


def _ctx(**kw):
    bar = Bar(time=1, open=100, high=102, low=99, close=101.5, volume=1000,
              buy_volume=600, sell_volume=400, delta=200, oi=50000, vwap=100.5)
    base = dict(symbol="NIFTY", bar=bar, agent_direction="LONG",
                market_state=MarketState.BALANCED, cvd_slope=0.5)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def _gates_with(setup_key):
    passed = [GateResult(1, True), GateResult(2, True),
              GateResult(3, True, "edge", setup_key=setup_key), GateResult(4, True)]
    return patch("quant.decision.decision_service.GatePipeline.evaluate",
                 return_value=passed)


def test_trend_setup_blocked_in_balanced_market():
    """BALANCED -> MEAN_REVERSION; a TRIPLE_A approval must not become a trade."""
    with _gates_with("TRIPLE_A"):
        d = DecisionService(min_rr=1.5).evaluate(_ctx(market_state=MarketState.BALANCED))
    assert not (d.approved and d.model_label == "Triple-A")


def test_trend_setup_allowed_in_imbalanced_market():
    with _gates_with("TRIPLE_A"):
        d = DecisionService(min_rr=1.5).evaluate(_ctx(market_state=MarketState.IMBALANCED))
    assert d.approved is True
