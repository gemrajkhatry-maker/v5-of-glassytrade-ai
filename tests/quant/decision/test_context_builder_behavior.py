# tests/quant/decision/test_context_builder_behavior.py
"""Tests for DecisionContextBuilder (Task 3).

Verifies that:
1. Market regime (IMBALANCED) alone does not fabricate setup approval.
2. DTO setup evidence fields map accurately into SetupEvidence.
3. Stale or incomplete evidence leaves setup_evidence incomplete.
"""

import pytest
from quant.decision.context_builder import DecisionContextBuilder
from quant.contracts.enums import MarketState
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


def test_imbalanced_context_has_no_complete_setup_without_sequence():
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "ofi": 0.5,
        "valueAreaHigh": 99.0,
        "valueAreaLow": 95.0,
    }
    ctx = builder.build(
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
    assert ctx.market_state == MarketState.IMBALANCED
    assert ctx.setup_evidence is None or not ctx.setup_evidence.is_complete()


def test_va_fade_dto_rejection_maps_to_complete_setup():
    """VA_FADE maps from real rejectionAtHigh/rejectionAtLow DTO keys.

    Regression: acceptance was hardcoded True via ``get("acceptance") or True``,
    so VA_FADE evidence could never complete (needs ``not acceptance``).
    """
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "BALANCED",
        "valueAreaHigh": 101.0,
        "valueAreaLow": 99.0,
        "poc": 100.0,
        "cvdSlope": -1.2,
        "rejectionAtHigh": True,
        "acceptanceAbove": False,
    }
    bar = _dummy_bar()
    bar = Bar(
        time=bar.time, open=bar.open, high=bar.high, low=bar.low,
        close=101.6, volume=bar.volume, buy_volume=bar.buy_volume,
        sell_volume=bar.sell_volume, delta=bar.delta,
    )
    ctx = builder.build(
        bar=bar,
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
    assert ctx.setup_evidence is not None
    assert ctx.setup_evidence.setup_type == "VA_FADE"
    assert ctx.setup_evidence.acceptance is False
    assert ctx.setup_evidence.rejection is True
    assert ctx.setup_evidence.is_complete() is True


def test_second_drive_dto_maps_to_complete_setup():
    """SECOND_DRIVE maps from real isSecondDrive + driveNumber DTO keys."""
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "valueAreaHigh": 99.0,
        "valueAreaLow": 95.0,
        "ofi": 0.5,
        "isSecondDrive": True,
        "driveNumber": 2,
        "rejectionAtHigh": True,
        "cvdSlope": 1.5,
    }
    ctx = builder.build(
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
    assert ctx.setup_evidence is not None
    assert ctx.setup_evidence.setup_type == "SECOND_DRIVE"
    assert ctx.setup_evidence.d1_rejected is True
    assert ctx.setup_evidence.is_complete() is True


def test_leg_lvn_derived_from_nearest_leg_lvns():
    """leg_lvn is the LVN nearest current price (no phantom legLvn key)."""
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "legLvns": [100.1, 102.0, 98.0],
        "absorptionSide": "SELL_ABSORBED",
        "cvdSlope": 1.5,
    }
    ctx = builder.build(
        bar=_dummy_bar(),  # close = 100.5 -> nearest LVN is 100.1
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
    assert ctx.leg_lvn == 100.1
    assert ctx.setup_evidence.level == 100.1


def test_context_builder_populates_bid_ask_from_order_book():
    from quant.contracts.value_objects import OrderBook, OrderBookLevel

    ob = OrderBook(bids=(OrderBookLevel(99.9, 10.0),), asks=(OrderBookLevel(100.1, 10.0),))
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.0), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=DummyRisk(), amt_dto={}, order_book=ob,
    )
    assert ctx.bid == 99.9
    assert ctx.ask == 100.1


def test_gate1_rejects_wide_spread():
    from quant.contracts.value_objects import OrderBook, OrderBookLevel
    from quant.decision.gates_session_position import gate_session_phase

    ob = OrderBook(bids=(OrderBookLevel(100.0, 10.0),), asks=(OrderBookLevel(101.0, 10.0),))
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.5), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=DummyRisk(), amt_dto={}, order_book=ob,
    )
    result = gate_session_phase(ctx)
    assert not result.passed
    assert "spread" in result.reason.lower()


def test_option_delta_reads_delta_normalized_option_key():
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.0), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=DummyRisk(), amt_dto={"deltaNormalizedOption": 0.15},
    )
    assert ctx.option_delta == 0.15
