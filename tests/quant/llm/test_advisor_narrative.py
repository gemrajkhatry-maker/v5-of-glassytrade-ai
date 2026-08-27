"""Unit checks for AMT_RULE narrative display accuracy."""

from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.llm.advisor import LLMAdvisor


def _ctx(**kw) -> DecisionContext:
    bar = Bar(
        time="2026-08-25T10:00:00+05:30",
        open=24150.0, high=24160.0, low=24140.0, close=24155.0,
        volume=1500.0, buy_volume=800.0, sell_volume=700.0, delta=100.0, vwap=24152.0,
    )
    return DecisionContext(
        symbol=kw.pop("symbol", "NIFTY"),
        bar=bar,
        market_state=kw.pop("market_state", MarketState.BALANCED),
        poc=kw.pop("poc", 24155.3),
        vah=kw.pop("vah", 24220.0),
        val=kw.pop("val", 24100.0),
        session_phase=kw.pop("session_phase", "PRIMARY"),
        cvd_slope=kw.pop("cvd_slope", 5.0),
        absorption_side=kw.pop("absorption_side", ""),
        **kw,
    )


def test_no_edge_at_poc_does_not_imply_imminent_long():
    """Bullish CVD at mid-value must say 'awaiting VAL', not 'Bullish order flow'."""
    adv = LLMAdvisor(emit_fn=None)
    out = adv._rule_based_narrative(_ctx(cvd_slope=5.0))
    assert out["direction"] == "FLAT"
    assert out["setup"] == "NO_EDGE"
    assert "mid-value near POC" in out["rationale"]
    assert "awaiting pullback to VAL" in out["rationale"]
    assert "Bullish order flow" not in out["rationale"]
    adv.shutdown()


def test_rule_based_emits_synchronously_without_model():
    """No model_path → sync emit so WS cannot race ahead of the narrative."""
    emitted = []
    adv = LLMAdvisor(emit_fn=lambda evt: emitted.append(evt))
    adv.on_context(_ctx())
    assert len(emitted) == 1
    assert emitted[0].decision["source"] == "AMT_RULE"
    adv.shutdown()
