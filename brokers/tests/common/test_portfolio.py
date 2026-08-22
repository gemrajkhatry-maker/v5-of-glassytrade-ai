"""Shared portfolio normalization (REF-3).

Both broker clients declare a ``PositionRowSpec`` (their REST row-key layout)
and delegate to ``common.portfolio.positions_from_rows``; ``normalize_account``
materializes never-None Money fields for both. These tests pin the shared
behavior for both dialects.
"""

from __future__ import annotations

from decimal import Decimal

from tradex_domain.execution import Account
from tradex_domain.value_objects import AccountId, InstrumentId, Money
from tradex_domain.wire import InstrumentRegistry

from tradex_brokers.common.portfolio import (
    PositionRowSpec,
    normalize_account,
    positions_from_rows,
)

_DHAN_SPEC = PositionRowSpec(
    instrument_keys=("securityId", "security_id"),
    quantity_keys=("netQty", "quantity"),
    avg_price_keys=("avgCostPrice", "averagePrice"),
    realized_keys=("realizedProfit",),
    unrealized_keys=("unrealizedProfit",),
)

_UPSTOX_SPEC = PositionRowSpec(
    instrument_keys=("instrument_token", "tradingsymbol"),
    quantity_keys=("quantity", "day_buy_quantity"),
    avg_price_keys=("average_price",),
    realized_keys=("realised",),
    unrealized_keys=("unrealised",),
)


def _registry() -> InstrumentRegistry:
    reg = InstrumentRegistry()
    iid = InstrumentId.equity("NSE", "RELIANCE")
    # First registered key becomes the provider key (Upstox token format);
    # the Dhan security id becomes an alias resolving to the same instrument.
    reg.register(iid, {"key": "NSE_EQ|RELIANCE", "asset_class": "EQUITY"})
    reg.add_alias("2885", iid)
    return reg


def test_positions_dhan_row_layout() -> None:
    rows = [
        {
            "securityId": "2885",
            "netQty": 10,
            "avgCostPrice": 2500.0,
            "realizedProfit": 100.0,
            "unrealizedProfit": 50.0,
        }
    ]
    positions = positions_from_rows(rows, registry=_registry(), spec=_DHAN_SPEC)
    assert len(positions) == 1
    assert positions[0].quantity.value == Decimal("10")
    assert positions[0].avg_price.value == Decimal("2500")
    assert positions[0].realized_pnl.amount == Decimal("100")
    assert positions[0].unrealized_pnl.amount == Decimal("50")


def test_positions_upstox_row_layout() -> None:
    rows = [
        {
            "instrument_token": "NSE_EQ|RELIANCE",
            "quantity": 10,
            "average_price": 2500.0,
            "realised": 100.0,
            "unrealised": 50.0,
        }
    ]
    positions = positions_from_rows(rows, registry=_registry(), spec=_UPSTOX_SPEC)
    assert len(positions) == 1
    assert positions[0].quantity.value == Decimal("10")
    assert positions[0].avg_price.value == Decimal("2500")
    assert positions[0].realized_pnl.amount == Decimal("100")


def test_positions_skips_unresolvable_and_non_rows() -> None:
    rows = [
        {"securityId": "not-in-registry", "netQty": 5},
        "garbage",
        None,
    ]
    assert positions_from_rows(rows, registry=_registry(), spec=_DHAN_SPEC) == []
    assert positions_from_rows("not-a-list", registry=_registry(), spec=_DHAN_SPEC) == []


def test_positions_defaults_zero_for_missing_numerics() -> None:
    rows = [{"securityId": "2885"}]  # no quantity/price/pnl fields
    positions = positions_from_rows(rows, registry=_registry(), spec=_DHAN_SPEC)
    assert len(positions) == 1
    assert positions[0].quantity.value == Decimal("0")
    assert positions[0].realized_pnl.amount == Decimal("0")
    assert positions[0].unrealized_pnl.amount == Decimal("0")


def test_normalize_account_materializes_none_money() -> None:
    raw = Account(
        account_id=AccountId(value="dhan"),
        balance=None,
        margin=None,
        equity=None,
    )
    normalized = normalize_account(raw)
    assert normalized.balance == Money(amount=Decimal("0"), currency="INR")
    assert normalized.margin == Money(amount=Decimal("0"), currency="INR")
    assert normalized.equity == Money(amount=Decimal("0"), currency="INR")


def test_normalize_account_preserves_values() -> None:
    raw = Account(
        account_id=AccountId(value="upstox"),
        balance=Money(amount=Decimal("50000"), currency="INR"),
        margin=Money(amount=Decimal("1000"), currency="INR"),
        equity=Money(amount=Decimal("51000"), currency="INR"),
    )
    normalized = normalize_account(raw)
    assert normalized is not raw
    assert normalized.balance == raw.balance
    assert normalized.margin == raw.margin
    assert normalized.equity == raw.equity


def test_position_instrument_built_from_registry() -> None:
    rows = [{"securityId": "2885", "netQty": 1}]
    positions = positions_from_rows(rows, registry=_registry(), spec=_DHAN_SPEC)
    inst = positions[0].instrument
    assert inst.symbol == "RELIANCE"
    assert inst.exchange.value == "NSE"
