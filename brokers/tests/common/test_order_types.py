"""Shared order-type / order-id normalization (REF-4).

The Dhan and Upstox clients declare their native stop names and delegate the
mapping to ``common.order_types``; these tests pin the shared logic for both
dialects so a future domain-enum change can't silently break one broker.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from tradex_domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from tradex_domain.execution import Order, OrderRequest
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import OrderId, Price, Quantity

from tradex_brokers.common.order_types import (
    domain_order_type,
    map_order_type,
    native_order_type,
    response_order_id,
    stream_order_price,
)


def _request(order_type: OrderType, *, price: bool = False) -> OrderRequest:
    return OrderRequest(
        instrument=Equity.of("NSE", "RELIANCE"),
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=Quantity(value=Decimal("10")),
        price=Price(value=Decimal("100")) if price else None,
        time_in_force=TimeInForce.DAY,
    )


# ---------------------------------------------------------------------------
# native_order_type — domain -> wire, both dialects
# ---------------------------------------------------------------------------


def test_dhan_native_stop_mapping() -> None:
    assert native_order_type(
        _request(OrderType.STOP_LIMIT, price=True),
        base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == "STOP_LOSS"
    # Priced STOP collapses to the same wire string as STOP_LIMIT (Dhan).
    assert native_order_type(
        _request(OrderType.STOP, price=True),
        base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == "STOP_LOSS"
    assert native_order_type(
        _request(OrderType.STOP),
        base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == "STOP_LOSS_MARKET"
    assert native_order_type(
        _request(OrderType.MARKET),
        base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == "MARKET"


def test_upstox_native_stop_mapping() -> None:
    assert native_order_type(
        _request(OrderType.STOP_LIMIT, price=True), base="SL", market="SL-M"
    ) == "SL"
    assert native_order_type(
        _request(OrderType.STOP, price=True), base="SL", market="SL-M"
    ) == "SL"
    assert native_order_type(_request(OrderType.STOP), base="SL", market="SL-M") == "SL-M"


def test_map_order_type_matches_native() -> None:
    assert map_order_type(
        OrderType.STOP, has_price=False, base="X", market="Y"
    ) == "Y"
    assert map_order_type(OrderType.MARKET, has_price=False, base="X", market="Y") == "MARKET"


# ---------------------------------------------------------------------------
# domain_order_type — wire -> domain, both dialects
# ---------------------------------------------------------------------------


def test_dhan_domain_stop_mapping_price_disambiguates() -> None:
    # Dhan collapses STOP_LIMIT and priced STOP to "STOP_LOSS": with a price
    # the reverse maps to STOP_LIMIT, without it to STOP.
    assert domain_order_type(
        "STOP_LOSS", base="STOP_LOSS", market="STOP_LOSS_MARKET", has_price=True,
    ) == OrderType.STOP_LIMIT
    assert domain_order_type(
        "STOP_LOSS", base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == OrderType.STOP
    assert domain_order_type(
        "STOP_LOSS_MARKET", base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == OrderType.STOP
    assert domain_order_type(
        "MARKET", base="STOP_LOSS", market="STOP_LOSS_MARKET",
    ) == OrderType.MARKET


def test_upstox_domain_sl_always_stop_limit() -> None:
    # Upstox's wire "SL" always means stop-limit (base_is_stop_limit).
    assert domain_order_type(
        "SL", base="SL", market="SL-M", base_is_stop_limit=True,
    ) == OrderType.STOP_LIMIT
    assert domain_order_type(
        "SL-M", base="SL", market="SL-M", base_is_stop_limit=True,
    ) == OrderType.STOP
    assert domain_order_type(
        "MARKET", base="SL", market="SL-M", base_is_stop_limit=True,
    ) == OrderType.MARKET


# ---------------------------------------------------------------------------
# response_order_id — order-id extraction from provider rows
# ---------------------------------------------------------------------------


def test_response_order_id_snake_and_camel() -> None:
    assert response_order_id({"order_id": "a1"}, "X").value == "a1"
    assert response_order_id({"orderId": "a2"}, "X").value == "a2"
    # snake preferred when both present (mirrors both clients' fallback order).
    assert response_order_id({"order_id": "a", "orderId": "b"}, "X").value == "a"


def test_response_order_id_list_fallback() -> None:
    assert response_order_id({"order_ids": ["x", "y"]}, "X").value == "x"
    assert response_order_id({"orderIds": ["p"]}, "X").value == "p"
    # An empty id list is no id at all — the extraction must fail loudly.
    with pytest.raises(ValueError, match="missing order id"):
        response_order_id({"order_ids": []}, "X")


def test_response_order_id_missing_raises() -> None:
    with pytest.raises(ValueError, match="missing order id"):
        response_order_id({"tag": "abc"}, "Upstox ext")


def test_response_order_id_primary_override() -> None:
    # Dhan eDIS passes the authorization id as the primary override.
    row = {"authorizationId": "edis-1", "orderId": "o-1"}
    assert response_order_id(row, "Dhan eDIS", primary="edis-1").value == "edis-1"
    assert response_order_id(row, "Dhan eDIS", primary=None).value == "o-1"


def test_response_order_id_wraps_raw_id() -> None:
    result = response_order_id({"order_id": 12345}, "X")
    assert isinstance(result, OrderId)
    assert result.value == "12345"


# ---------------------------------------------------------------------------
# stream_order_price — traded-price override on live order-update rows
# ---------------------------------------------------------------------------


def _order(status: OrderStatus = OrderStatus.FILLED, price: str = "2500") -> Order:
    return Order(
        order_id=OrderId(value="o-1"),
        instrument=Equity.of("NSE", "RELIANCE"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(value=Decimal("10")),
        price=Price(value=Decimal(price)),
        time_in_force=TimeInForce.DAY,
        status=status,
    )


def test_stream_order_price_overrides_fill_price() -> None:
    # Dhan dialect: tradedPrice / traded_price keys, empty-string excluded.
    row = {"tradedPrice": "2501.5"}
    result = stream_order_price(
        _order(), row, traded_keys=("tradedPrice", "traded_price"),
    )
    assert result is not _order()
    assert result.price.value == Decimal("2501.5")
    # Fallback key form.
    result2 = stream_order_price(
        _order(), {"traded_price": "2502"}, traded_keys=("tradedPrice", "traded_price"),
    )
    assert result2.price.value == Decimal("2502")


def test_stream_order_price_leaves_non_fills_untouched() -> None:
    row = {"tradedPrice": "2501.5"}
    result = stream_order_price(
        _order(status=OrderStatus.ACK), row,
        traded_keys=("tradedPrice", "traded_price"),
    )
    assert result.price.value == Decimal("2500")  # limit price kept


def test_stream_order_price_upstox_dialect() -> None:
    # Upstox dialect: average_price key, zero excluded.
    result = stream_order_price(
        _order(), {"average_price": 2501.0},
        traded_keys=("average_price",), excluded=(None, "", 0),
    )
    assert result.price.value == Decimal("2501")
    # Zero traded price is treated as absent (Upstox policy).
    zero = stream_order_price(
        _order(), {"average_price": 0},
        traded_keys=("average_price",), excluded=(None, "", 0),
    )
    assert zero.price.value == Decimal("2500")
    # Missing key leaves the limit price.
    missing = stream_order_price(
        _order(), {},
        traded_keys=("average_price",), excluded=(None, "", 0),
    )
    assert missing.price.value == Decimal("2500")


def test_stream_order_price_partially_filled_overrides() -> None:
    result = stream_order_price(
        _order(status=OrderStatus.PARTIALLY_FILLED), {"tradedPrice": "2499"},
        traded_keys=("tradedPrice", "traded_price"),
    )
    assert result.price.value == Decimal("2499")
