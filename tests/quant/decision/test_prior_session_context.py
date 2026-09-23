# tests/quant/decision/test_prior_session_context.py
"""Prior-session VAH/VAL/gapType/openingBias map onto DecisionContext (Task 4)."""

from quant.decision.context_builder import DecisionContextBuilder
from quant.bars import Bar


class DummyRisk:
    equity = 1_000_000.0
    risk_per_trade_pct = 0.01
    halted = False
    consecutive_losses = 0


def _dummy_bar(close=100.5):
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=100.0,
        high=101.0,
        low=99.0,
        close=close,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
    )


def test_prior_session_fields_mapped():
    dto = {
        "marketState": "BALANCED",
        "valueAreaHigh": 101.0,
        "valueAreaLow": 99.0,
        "priorPoc": 100.0,
        "priorVah": 102.5,
        "priorVal": 97.5,
        "gapType": "GAP_UP",
        "openingBias": "BULLISH",
    }
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )
    assert ctx.prior_poc == 100.0
    assert ctx.prior_vah == 102.5
    assert ctx.prior_val == 97.5
    assert ctx.gap_type == "GAP_UP"
    assert ctx.opening_bias == "BULLISH"


def test_prior_session_fields_default_when_absent():
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto={},
    )
    assert ctx.prior_vah == 0.0
    assert ctx.prior_val == 0.0
    assert ctx.gap_type == ""
    assert ctx.opening_bias == ""
