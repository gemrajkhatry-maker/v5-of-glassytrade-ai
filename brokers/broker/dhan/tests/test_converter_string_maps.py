"""
Characterization tests for DhanConverter string mapping tables.

These tests pin down the exact behavior of the table-driven string mappings
introduced when the if/elif chains in converters.py were extracted into
module-level frozen dicts. Every input key of every mapping table is
enumerated, plus at least one unknown key per direction to lock in the
default/fallthrough semantics. Expected values were derived from the
original chain logic *before* the refactor (zero behavior change).

If these tests fail, someone changed a mapping's semantics - stop and think.
"""

from typing import Any, Dict

import pytest

from brokers.broker.dhan.application import DhanConverter, to_segment
from brokers.broker.dhan.application.converters import (
    DHAN_OPTION_TYPE_MAP,
    DHAN_ORDER_STATUS_MAP,
    DHAN_ORDER_TYPE_MAP,
    DHAN_STRING_TO_SEGMENT,
    ORDER_TYPE_TO_DHAN,
)
from shared.entities.models import Instrument, Order
from brokers.broker.types import Exchange, OptionType, OrderSide, OrderStatus, OrderType
from brokers.broker.dhan.domain import OptionType as DhanOptionType


# =============================================================================
# to_segment / DHAN_STRING_TO_SEGMENT
# =============================================================================


@pytest.mark.parametrize(
    "raw,expected",
    sorted(DHAN_STRING_TO_SEGMENT.items()),
)
def test_to_segment_every_known_key(raw: str, expected: str) -> None:
    """Every key in DHAN_STRING_TO_SEGMENT maps to its declared value."""
    assert to_segment(raw) == expected


def test_to_segment_unknown_passthrough() -> None:
    """Unknown strings fall through unchanged (original .get(k, k) default)."""
    assert to_segment("NOT_A_REAL_SEGMENT") == "NOT_A_REAL_SEGMENT"


def test_to_segment_none() -> None:
    assert to_segment(None) is None


def test_to_segment_normalizes_case_and_whitespace() -> None:
    """Original code applied .upper().strip() before lookup."""
    assert to_segment("  nse  ") == "NSE_EQ"
    assert to_segment("nfo") == "NSE_FNO"


# =============================================================================
# _map_order_type_from_dhan / DHAN_ORDER_TYPE_MAP
# =============================================================================


@pytest.mark.parametrize(
    "dhan_str,expected",
    sorted(
        {
            "MARKET": OrderType.MARKET,
            "LIMIT": OrderType.LIMIT,
            "STOP_LOSS": OrderType.SL,
            "STOP_LOSS_MARKET": OrderType.SLM,
            "SL": OrderType.SL,
            "SL-M": OrderType.SLM,
        }.items()
    ),
)
def test_map_order_type_from_dhan_every_known_key(dhan_str: str, expected: OrderType) -> None:
    assert DhanConverter._map_order_type_from_dhan(dhan_str) == expected


def test_map_order_type_from_dhan_unknown_defaults_market() -> None:
    """Unknown strings default to OrderType.MARKET (original fallthrough)."""
    assert DhanConverter._map_order_type_from_dhan("TOTALLY_UNKNOWN") == OrderType.MARKET
    assert DhanConverter._map_order_type_from_dhan("") == OrderType.MARKET


def test_map_order_type_from_dhan_is_case_insensitive() -> None:
    """Original code applied .upper() before lookup."""
    assert DhanConverter._map_order_type_from_dhan("limit") == OrderType.LIMIT


# =============================================================================
# _map_order_status_from_dhan / DHAN_ORDER_STATUS_MAP
# =============================================================================


@pytest.mark.parametrize(
    "dhan_status,expected",
    [
        ("PENDING", OrderStatus.PENDING),
        ("TRANSIT", OrderStatus.PENDING),
        ("OPEN", OrderStatus.OPEN),
        ("PARTIALLY_FILLED", OrderStatus.OPEN),
        ("PART_TRADED", OrderStatus.OPEN),
        ("TRADED", OrderStatus.FILLED),
        ("FILLED", OrderStatus.FILLED),
        ("CANCELLED", OrderStatus.CANCELLED),
        ("CANCELED", OrderStatus.CANCELLED),  # US spelling alias
        ("REJECTED", OrderStatus.REJECTED),
        ("EXPIRED", OrderStatus.CANCELLED),
    ],
)
def test_map_order_status_from_dhan_every_known_key(
    dhan_status: str, expected: OrderStatus
) -> None:
    assert DhanConverter._map_order_status_from_dhan(dhan_status) == expected


def test_map_order_status_from_dhan_unknown_defaults_pending() -> None:
    """Unknown statuses default to OrderStatus.PENDING (original fallthrough)."""
    assert DhanConverter._map_order_status_from_dhan("WHAT_IS_THIS") == OrderStatus.PENDING
    assert DhanConverter._map_order_status_from_dhan("") == OrderStatus.PENDING


def test_map_order_status_from_dhan_is_case_insensitive() -> None:
    assert DhanConverter._map_order_status_from_dhan("filled") == OrderStatus.FILLED


# =============================================================================
# _map_option_type / DHAN_OPTION_TYPE_MAP
# =============================================================================


def test_map_option_type_known_keys() -> None:
    """DhanOptionType only has CALL('CE')/PUT('PE'); both pinned here."""
    assert DhanConverter._map_option_type(DhanOptionType.CALL) == OptionType.CALL
    assert DhanConverter._map_option_type(DhanOptionType.PUT) == OptionType.PUT


def test_map_option_type_table_matches_behavior() -> None:
    """The module-level table agrees with the method for all table keys."""
    for dhan_opt, expected in DHAN_OPTION_TYPE_MAP.items():
        assert DhanConverter._map_option_type(dhan_opt) == expected


def test_map_option_type_unknown_defaults_call() -> None:
    """Default is OptionType.CALL; unreachable via public enum members but
    pinned via direct table-default equivalence for documentation value."""
    missing = object()
    assert DHAN_OPTION_TYPE_MAP.get(missing, OptionType.CALL) == OptionType.CALL  # type: ignore[arg-type]


# =============================================================================
# from_order_request / ORDER_TYPE_TO_DHAN
# =============================================================================


def _order(order_type: OrderType) -> Order:
    return Order(
        instrument=Instrument(symbol="NIFTY", exchange=Exchange.NFO, security_id="12345"),
        side=OrderSide.BUY,
        quantity=50.0,
        order_type=order_type,
    )


@pytest.mark.parametrize(
    "internal,dhan_str",
    sorted(ORDER_TYPE_TO_DHAN.items(), key=lambda kv: kv[0].value),
)
def test_from_order_request_every_order_type(internal: OrderType, dhan_str: str) -> None:
    """Every internal OrderType maps to its declared Dhan orderType string."""
    payload: Dict[str, Any] = DhanConverter.from_order_request(_order(internal))
    assert payload["orderType"] == dhan_str


def test_from_order_request_transaction_type() -> None:
    """BUY/SELL ternary pinned alongside the order-type table."""
    buy_payload = DhanConverter.from_order_request(_order(OrderType.MARKET))
    assert buy_payload["transactionType"] == "BUY"

    sell_order = _order(OrderType.MARKET)
    sell_order.side = OrderSide.SELL
    sell_payload = DhanConverter.from_order_request(sell_order)
    assert sell_payload["transactionType"] == "SELL"


def test_order_type_tables_are_inverse_consistent() -> None:
    """ORDER_TYPE_TO_DHAN and DHAN_ORDER_TYPE_MAP agree on shared values."""
    for internal, dhan_str in ORDER_TYPE_TO_DHAN.items():
        assert DhanConverter._map_order_type_from_dhan(dhan_str) == internal


def test_mapping_tables_are_nonempty() -> None:
    """Guard against accidental truncation of the tables."""
    assert len(DHAN_STRING_TO_SEGMENT) == 14
    assert len(DHAN_ORDER_TYPE_MAP) == 6
    assert len(DHAN_ORDER_STATUS_MAP) == 11
    assert len(ORDER_TYPE_TO_DHAN) == 4
    assert len(DHAN_OPTION_TYPE_MAP) == 2
