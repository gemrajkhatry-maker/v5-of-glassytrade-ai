"""One selector: auction state picks the model, certified evidence may override."""
from quant.contracts.enums import MarketState
from quant.decision.model_router import (
    TREND, MEAN_REVERSION, allows, select_model, setup_model,
)
from quant.decision.setup_state import SetupEvidence


def _ctx(**kw):
    from quant.decision.context import DecisionContext
    base = dict(market_state=MarketState.BALANCED)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                              if k in DecisionContext.__dataclass_fields__})


def _ev(setup_type, direction="LONG", **kw):
    ev = SetupEvidence(setup_type=setup_type, direction=direction,
                       cvd_agrees=True, **kw)
    return ev


def test_setup_model_mapping():
    assert setup_model("TRIPLE_A") == TREND
    assert setup_model("LVN_SNIPER") == TREND
    assert setup_model("INITIATIVE") == TREND
    assert setup_model("SQUEEZE") == TREND
    assert setup_model("SECOND_DRIVE") == TREND
    assert setup_model("VA_FADE") == MEAN_REVERSION
    assert setup_model("NOPE") is None


def test_balanced_selects_mean_reversion():
    assert select_model(_ctx(market_state=MarketState.BALANCED)) == MEAN_REVERSION


def test_imbalanced_selects_trend():
    assert select_model(_ctx(market_state=MarketState.IMBALANCED)) == TREND


def test_complete_va_fade_evidence_overrides_imbalanced():
    ev = _ev("VA_FADE", rejection=True, acceptance=False)
    assert ev.is_complete()
    assert select_model(_ctx(market_state=MarketState.IMBALANCED,
                             setup_evidence=ev)) == MEAN_REVERSION


def test_initiative_break_overrides_balanced():
    assert select_model(_ctx(market_state=MarketState.BALANCED,
                             break_type="INITIATIVE", break_direction="UP")) == TREND


def test_incomplete_evidence_does_not_override():
    ev = _ev("VA_FADE", rejection=False, acceptance=False)
    assert not ev.is_complete()
    assert select_model(_ctx(market_state=MarketState.IMBALANCED,
                             setup_evidence=ev)) == TREND


def test_allows_is_model_scoped():
    assert allows("VA_FADE", MEAN_REVERSION)
    assert not allows("VA_FADE", TREND)
    assert allows("TRIPLE_A", TREND)
    assert not allows("TRIPLE_A", MEAN_REVERSION)
    assert not allows("UNKNOWN", TREND)
