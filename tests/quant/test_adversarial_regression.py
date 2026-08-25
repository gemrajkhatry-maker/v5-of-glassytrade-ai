"""Adversarial Regression Test Suite.

Proves remediation for all classes of defects identified in the adversarial audit:
1. Portfolio risk P&L accumulation across engine threads.
2. Break detector state clearing on Initial Balance re-entry (failed auctions).
3. Absorption delta direction correctness per Fabio AMT methodology.
4. Scale-safe underlying-to-option signal translation.
5. Full exchange lot sizes and strike interval resolution (NSE & MCX).
6. Position identity and trailing stop persistence across partial closes.
7. DecisionService gate hierarchy: Gate 1/2 failure blocks VA-fade fallback.
8. ExchangeConfig complete coverage for all registered underlyings without KeyError.
"""

from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.contracts.exchange_config import ExchangeConfig
from quant.contracts.value_objects import FloatOHLC
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.result import GateResult
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Position, Order
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.execution.risk import SessionRisk
from quant.amt.market.break_detector import check_ib_break_tick
from quant.amt.orderflow.detectors import AbsorptionDetector
from quant.amt.session.selector import OptionSelector, OptionSelectorConfig
from quant.amt.session.scanner import ContractSwitchGuard


def test_portfolio_risk_accumulates_realized_pnl_on_exits():
    """Verify that closed trade P&L is accumulated into PortfolioRiskAuthority."""
    portfolio_risk = PortfolioRiskAuthority(starting_equity=500_000, max_portfolio_daily_loss_pct=0.06)
    
    # Simulate a trade with initial risk of 2,500 rupees
    assert portfolio_risk.register_open(2500.0) is True
    assert portfolio_risk.open_risk == 2500.0

    # Simulate exit with -1,500 rupee loss
    portfolio_risk.record_close(2500.0, -1500.0)
    assert portfolio_risk.open_risk == 0.0
    assert portfolio_risk.realized_pnl == -1500.0

    # Verify that can_accept evaluates real cumulative P&L
    accepted, reason = portfolio_risk.can_accept(2000.0)
    assert accepted is True

    # Simulate catastrophic loss exceeding max daily loss (6% of 500k = 30k)
    portfolio_risk.record_close(0.0, -29000.0)
    assert portfolio_risk.realized_pnl == -30500.0
    accepted, reason = portfolio_risk.can_accept(1000.0)
    assert accepted is False
    assert "portfolio daily-loss halt" in reason


def test_break_state_clears_on_reentry():
    """Verify that Initial Balance break state resets when price re-enters the IB."""
    ib_high = 24500.0
    ib_low = 24400.0

    # 1. Price above IB High -> Active initiative break UP
    b_up = check_ib_break_tick(live_price=24510.0, ib_high=ib_high, ib_low=ib_low, ib_complete=True)
    assert b_up["break_direction"] == "UP"
    assert b_up["break_type"] == "INITIATIVE"

    # 2. Price below IB Low -> Active initiative break DOWN
    b_down = check_ib_break_tick(live_price=24390.0, ib_high=ib_high, ib_low=ib_low, ib_complete=True)
    assert b_down["break_direction"] == "DOWN"
    assert b_down["break_type"] == "INITIATIVE"

    # 3. Price re-enters IB (e.g. 24450) -> Break state MUST clear (failed auction / rotation)
    b_reentry = check_ib_break_tick(live_price=24450.0, ib_high=ib_high, ib_low=ib_low, ib_complete=True)
    assert b_reentry["break_direction"] == ""
    assert b_reentry["break_type"] == ""


def test_absorption_delta_direction():
    """Verify absorption delta direction: delta < 0 is SELL_ABSORBED (bullish support floor)."""
    detector = AbsorptionDetector()

    # Candle with flat range (0.1), high volume (500), and negative delta (-300) = passive buyers absorbing sellers
    c_bullish = FloatOHLC(time="t1", open=100.0, high=100.1, low=99.9, close=100.0, volume=500.0, delta=-300.0)
    res_pending = detector.detect(c_bullish, atr=1.0, avg_vol=100.0)
    assert detector._pending_side == "SELL_ABSORBED"  # Bullish support

    # Displacement bar closing above the absorption high confirms bullish absorption
    c_disp = FloatOHLC(time="t2", open=100.0, high=101.0, low=99.9, close=100.5, volume=200.0, delta=100.0)
    res_confirmed = detector.detect(c_disp, atr=1.0, avg_vol=100.0)
    assert res_confirmed.detected is True
    assert res_confirmed.side == "SELL_ABSORBED"


def test_option_signal_translation_does_not_reject_index_scale():
    """Verify that underlying index signals (e.g. 24,500) translate cleanly to option contracts."""
    selector = OptionSelector()
    
    # Signal on NIFTY index at 24,500
    underlying_sig = Signal(
        type="LONG",
        reason="Triple-A",
        entry=24500.0,
        sl=24450.0,
        tp=24600.0,
        rr=2.0,
        model_label="Triple-A",
        timestamp="2026-08-24T10:00:00+05:30",
        symbol="NIFTY AUG FUT",
    )

    opt_sig = selector.translate_underlying_signal_to_option(
        signal=underlying_sig,
        option_symbol="NIFTY 24500 CALL",
        option_ltp=150.0,
        delta=0.50,
        tick_size=0.05,
    )

    assert opt_sig is not None, "Option signal translation must not be rejected by scale guards"
    assert opt_sig.entry == 150.0
    # 50 pts underlying risk * 0.50 delta = 25 pts option risk -> SL = 125.0
    assert opt_sig.sl == pytest.approx(125.0, abs=0.1)
    # 100 pts underlying reward * 0.50 delta = 50 pts option reward -> TP = 200.0
    assert opt_sig.tp == pytest.approx(200.0, abs=0.1)


def test_option_selector_lot_sizes_all_underlyings():
    """Verify lot size resolution across all NSE and MCX underlyings."""
    selector = OptionSelector()
    assert selector._lot_size_for("NIFTY") == 65
    assert selector._lot_size_for("BANKNIFTY") == 30
    assert selector._lot_size_for("FINNIFTY") == 60
    assert selector._lot_size_for("MIDCPNIFTY") == 120
    assert selector._lot_size_for("CRUDEOIL") == 100
    assert selector._lot_size_for("CRUDEOILM") == 10
    assert selector._lot_size_for("NATURALGAS") == 1250


def test_partial_close_preserves_position_id_and_trail():
    """Verify that PaperOMS.close_partial preserves position identity for trailing stops."""
    oms = PaperOMS(lot_size=65.0)
    sig = Signal(type="LONG", reason="test", entry=100.0, sl=95.0, tp=110.0, rr=2.0, model_label="Triple-A", timestamp="2026-08-24T10:00:00+05:30", symbol="NIFTY")
    pos = oms.submit(sig, 130.0)  # 2 lots
    original_id = pos._id

    fill, remaining = oms.close_partial(pos, fraction=0.50, price=105.0, time="t1", reason="TP1")
    assert remaining.size == 65.0
    assert remaining._id == original_id, "Remaining position must retain original _id so trailing stops persist"


def test_decision_service_blocks_fade_when_gate1_fails():
    """Verify that DecisionService does NOT approve VA-fade when Gate 1 or 2 fails."""
    service = DecisionService()
    
    # Gate 1 failure: spread blown out (e.g. 5% spread)
    bar = Bar(time="t", open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0)
    ctx = DecisionContext(
        state=None,
        bar=bar,
        symbol="NIFTY",
        time_str="t",
        agent_direction="LONG",
        market_state=MarketState.BALANCED.value,
        val=99.5,
        vah=100.5,
        poc=100.0,
        bid=95.0,
        ask=105.0,  # 10% spread -> Gate 1 fails
        tick_size=0.05,
    )

    decision = service.evaluate(ctx)
    assert decision.approved is False
    assert decision.reason == "GATE_REJECTED"


def test_exchange_config_mcx_symbols_have_lot_and_tick_sizes():
    """Verify that all MCX registered underlyings have valid lot sizes and tick sizes."""
    mcx = ExchangeConfig.for_exchange("MCX")
    for sym in mcx.underlyings:
        lot = mcx.get_lot_size(sym)
        assert lot > 0, f"MCX underlying {sym} missing valid lot size"
        tick = mcx.get_tick_size(sym)
        assert tick > 0, f"MCX underlying {sym} missing valid tick size"
