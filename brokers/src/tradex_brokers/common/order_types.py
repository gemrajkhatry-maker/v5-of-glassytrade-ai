"""Shared broker order normalization — order-type and order-id mappings.

Both broker adapters map domain :class:`OrderType` values to their native wire
strings (STOP_LIMIT/STOP collapse to a broker-specific stop variant) and back
the other way. These mirrored mappings must change in lockstep whenever the
domain enum grows, so the logic lives here once: each client declares its
native stop names and the shared helpers do the mapping. Response order-id
extraction follows the same lockstep pattern (``order_id``/``orderId`` keys
plus a list fallback) and is unified here as well.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from tradex_domain.enums import OrderStatus, OrderType
from tradex_domain.execution import Order, OrderRequest
from tradex_domain.value_objects import OrderId

from tradex_brokers.common.instruments import as_price


def map_order_type(
    order_type: OrderType,
    *,
    has_price: bool,
    base: str,
    market: str,
) -> str:
    """Map a domain :class:`OrderType` to a broker-native order-type string.

    Parameters
    ----------
    order_type:
        The domain order type to translate.
    has_price:
        Whether a limit price is present (STOP with a price is a stop-limit
        variant on both brokers).
    base:
        The broker's native string for a stop order.
    market:
        The broker's native string for a stop-market order (no price).
    """
    if order_type is OrderType.STOP_LIMIT:
        return base
    if order_type is OrderType.STOP:
        return base if has_price else market
    return order_type.value


def native_order_type(request: OrderRequest, *, base: str, market: str) -> str:
    """Map a domain :class:`OrderRequest`'s type to a broker-native string."""
    return map_order_type(
        request.order_type,
        has_price=request.price is not None,
        base=base,
        market=market,
    )


def domain_order_type(
    value: str,
    *,
    base: str,
    market: str,
    has_price: bool = False,
    base_is_stop_limit: bool = False,
) -> OrderType:
    """Map a broker-native order-type string back to :class:`OrderType`.

    ``base`` with a price is ambiguous on both brokers (STOP_LIMIT and a
    priced STOP collapse to the same wire string), so ``has_price``
    disambiguates the reverse direction exactly as the per-broker parsers did.
    A broker whose wire format always means stop-limit for ``base`` (Upstox's
    ``SL``) sets ``base_is_stop_limit`` instead.
    """
    native = value.upper()
    if native == base:
        if base_is_stop_limit:
            return OrderType.STOP_LIMIT
        return OrderType.STOP_LIMIT if has_price else OrderType.STOP
    if native == market:
        return OrderType.STOP
    return OrderType(native)


def _first_present(row: Mapping[str, Any], keys: Sequence[str]) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def stream_order_price(
    order: Order,
    row: Mapping[str, Any],
    *,
    traded_keys: Sequence[str],
    excluded: tuple[object, ...] = (None, ""),
) -> Order:
    """Override an order-update row's fill price with the traded price.

    Order-stream updates report the limit price; fills actually trade at the
    traded/average price. For ``FILLED``/``PARTIALLY_FILLED`` rows the order's
    price is replaced with the traded price so the fill bridge prices fills
    at the real trade price. Both brokers mirror this logic with different
    row keys (Dhan ``tradedPrice``, Upstox ``average_price``); ``excluded``
    preserves each broker's empty-value policy (Upstox also excludes ``0``).
    """
    traded = _first_present(row, traded_keys)
    if (
        traded not in excluded
        and order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
    ):
        return replace(order, price=as_price(traded))
    return order


def response_order_id(
    row: Mapping[str, Any],
    provider: str,
    *,
    primary: object | None = None,
) -> OrderId:
    """Extract the order id from a provider response row.

    Checks the row's ``order_id``/``orderId`` keys (or the caller-supplied
    ``primary`` override for provider-specific keys), then the plural list
    forms, raising ``ValueError`` when no id is present.
    """
    raw = primary
    if raw is None:
        raw = row.get("order_id", row.get("orderId"))
    if raw is None:
        ids = row.get("order_ids", row.get("orderIds"))
        raw = ids[0] if isinstance(ids, list) and ids else None
    if raw is None:
        raise ValueError(f"{provider} extension response missing order id")
    return OrderId(value=str(raw))


__all__ = [
    "domain_order_type",
    "map_order_type",
    "native_order_type",
    "response_order_id",
    "stream_order_price",
]
