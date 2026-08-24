"""Tests for OrderResult status coercion (unknown provider statuses)."""

from __future__ import annotations

from tradex_domain.enums import OrderStatus
from tradex_domain.execution import OrderResult
from tradex_domain.value_objects import OrderId


def test_order_result_coerces_string_status() -> None:
    result = OrderResult(order_id=OrderId(value="o1"), status="FILLED")  # type: ignore[arg-type]
    assert result.status is OrderStatus.FILLED


def test_order_result_unknown_for_bogus_status() -> None:
    """A provider status the domain doesn't know must degrade to UNKNOWN,
    never raise or fabricate a wrong state."""
    result = OrderResult(
        order_id=OrderId(value="o1"), status="NOT_A_REAL_STATUS"  # type: ignore[arg-type]
    )
    assert result.status is OrderStatus.UNKNOWN


def test_order_result_defaults_to_unknown() -> None:
    assert OrderResult(order_id=OrderId(value="o1")).status is OrderStatus.UNKNOWN
