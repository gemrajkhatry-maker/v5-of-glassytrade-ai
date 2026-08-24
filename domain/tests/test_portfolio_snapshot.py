"""Tests for PortfolioSnapshot currency derivation."""

from __future__ import annotations

from decimal import Decimal

from tradex_domain.enums import ExchangeId
from tradex_domain.execution import Position, PortfolioSnapshot
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import InstrumentId, Money, Price, Quantity


def _usd_equity() -> Equity:
    return Equity(
        instrument_id=InstrumentId.equity("NSE", "USDSTOCK"),
        symbol="USDSTOCK",
        exchange=ExchangeId("NSE"),
        currency="USD",
    )


def test_total_pnl_currency_derived_from_positions() -> None:
    pos = Position(
        instrument=_usd_equity(),
        quantity=Quantity(Decimal("10")),
        avg_price=Price(Decimal("100")),
        realized_pnl=Money(Decimal("5"), currency="USD"),
        unrealized_pnl=Money(Decimal("3"), currency="USD"),
    )
    snapshot = PortfolioSnapshot(positions=[pos])
    assert snapshot.total_pnl.currency == "USD"
    assert snapshot.total_pnl.amount == Decimal("8")


def test_total_pnl_empty_defaults_to_inr() -> None:
    assert PortfolioSnapshot().total_pnl.currency == "INR"
