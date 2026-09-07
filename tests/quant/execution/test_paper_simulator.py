"""Paper execution simulator contract tests."""

from dataclasses import asdict

import pytest

from quant.contracts.contracts import ContractRef
from quant.execution.paper_simulator import (
    PaperExecutionSimulator,
    PaperOrderStatus,
)


def _contract():
    return ContractRef(
        symbol="NIFTY 30 SEP 25000 CE",
        exchange="NFO",
        expiry="2026-09-30",
        strike=25000,
        option_type="CE",
        lot_size=65,
        tick_size=0.05,
    )


def test_paper_submit_fills_at_reference_price_and_lot_size():
    simulator = PaperExecutionSimulator()

    fill = simulator.submit(
        order_id="paper-1",
        contract=_contract(),
        side="BUY",
        quantity=130,
        reference_price=100.0,
    )

    assert fill.status is PaperOrderStatus.FILLED
    assert fill.filled_quantity == 130
    assert fill.fill_price == 100.0
    assert fill.instrument_key.startswith("NFO:")
    assert "security_id" not in asdict(fill)


def test_duplicate_paper_submit_is_idempotent():
    simulator = PaperExecutionSimulator()
    kwargs = dict(
        order_id="paper-duplicate",
        contract=_contract(),
        side="BUY",
        quantity=65,
        reference_price=100.0,
    )

    first = simulator.submit(**kwargs)
    second = simulator.submit(**kwargs)

    assert second == first
    assert simulator.fills == (first,)


def test_reusing_order_id_with_different_request_is_rejected():
    simulator = PaperExecutionSimulator()
    simulator.submit(
        order_id="paper-conflict",
        contract=_contract(),
        side="BUY",
        quantity=65,
        reference_price=100.0,
    )

    with pytest.raises(ValueError, match="already exists"):
        simulator.submit(
            order_id="paper-conflict",
            contract=_contract(),
            side="SELL",
            quantity=65,
            reference_price=100.0,
        )


def test_invalid_non_lot_quantity_is_rejected():
    with pytest.raises(ValueError, match="lot"):
        PaperExecutionSimulator().submit(
            order_id="paper-invalid-lot",
            contract=_contract(),
            side="BUY",
            quantity=32,
            reference_price=100.0,
        )


def test_bid_ask_mode_uses_executable_side():
    simulator = PaperExecutionSimulator(fill_mode="bid_ask")

    buy = simulator.submit(
        order_id="paper-buy-quote",
        contract=_contract(),
        side="BUY",
        quantity=65,
        reference_price=100.0,
        bid=99.8,
        ask=100.2,
    )
    sell = simulator.submit(
        order_id="paper-sell-quote",
        contract=_contract(),
        side="SELL",
        quantity=65,
        reference_price=100.0,
        bid=99.8,
        ask=100.2,
    )

    assert buy.fill_price == 100.2
    assert sell.fill_price == 99.8


def test_fill_exposes_cost_breakdown_for_authoritative_net_pnl():
    simulator = PaperExecutionSimulator(slippage_bps=15.0)

    fill = simulator.submit(
        order_id="paper-costs",
        contract=_contract(),
        side="BUY",
        quantity=65,
        reference_price=100.0,
    )

    assert fill.costs.total > 0.0
    assert fill.net_cash_flow < 0.0
