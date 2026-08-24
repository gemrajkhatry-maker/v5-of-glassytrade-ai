"""Shared broker portfolio normalization — positions + account snapshots.

Both broker adapters translate raw REST rows into domain :class:`Position` /
:class:`Account` objects. The row layouts differ per broker (Dhan uses
``securityId``/``netQty``, Upstox ``instrument_token``/``quantity``) but the
mapping shape is identical — resolve the instrument via the registry, wrap the
numeric strings into ``Quantity``/``Price``/``Money``, skip unresolvable rows.
The loop lives here once and each broker declares its row-key layout as a
:class:`PositionRowSpec`; the account normalization (never-None ``Money``
fields) is byte-identical across brokers and is shared as well.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from tradex_domain.execution import Account, Position
from tradex_domain.value_objects import Money, Quantity
from tradex_domain.wire import InstrumentRegistry

from tradex_brokers.common.instruments import (
    as_decimal,
    as_price,
    instrument_from_registry,
)


@dataclass(frozen=True)
class PositionRowSpec:
    """Per-broker row-key layout for position rows.

    Each field is an ordered tuple of candidate keys; the first key present in
    the row wins (mirroring the per-broker ``row.get(a, row.get(b, default))``
    chains exactly).
    """

    instrument_keys: tuple[str, ...]
    quantity_keys: tuple[str, ...]
    avg_price_keys: tuple[str, ...]
    realized_keys: tuple[str, ...]
    unrealized_keys: tuple[str, ...]


def _first(
    row: Mapping[str, Any],
    keys: Sequence[str],
    default: object = None,
) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return default


def positions_from_rows(
    rows: object,
    *,
    registry: InstrumentRegistry,
    spec: PositionRowSpec,
) -> list[Position]:
    """Map raw broker rows to domain :class:`Position` objects.

    Rows whose instrument cannot be resolved through *registry* are skipped
    (matching the per-broker parsers).
    """
    if not isinstance(rows, list):
        return []
    out: list[Position] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        iid = registry.resolve(
            str(_first(row, spec.instrument_keys, default=""))
        )
        if iid is None:
            continue
        out.append(
            Position(
                instrument=instrument_from_registry(registry, iid),
                quantity=Quantity(
                    value=as_decimal(
                        str(_first(row, spec.quantity_keys, default=0))
                    )
                ),
                avg_price=as_price(_first(row, spec.avg_price_keys, default=0)),
                realized_pnl=Money(
                    amount=as_decimal(
                        str(_first(row, spec.realized_keys, default=0))
                    ),
                    currency="INR",
                ),
                unrealized_pnl=Money(
                    amount=as_decimal(
                        str(_first(row, spec.unrealized_keys, default=0))
                    ),
                    currency="INR",
                ),
            )
        )
    return out


def normalize_account(snapshot: Account) -> Account:
    """Return *snapshot* with every ``Money`` field materialized (never None)."""
    return Account(
        account_id=snapshot.account_id,
        balance=snapshot.balance or Money(amount=Decimal("0"), currency="INR"),
        margin=snapshot.margin or Money(amount=Decimal("0"), currency="INR"),
        equity=snapshot.equity or Money(amount=Decimal("0"), currency="INR"),
    )


__all__ = ["PositionRowSpec", "normalize_account", "positions_from_rows"]
