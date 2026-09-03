from brokers.broker.types import OrderStatus
from brokers.broker.dhan.domain.order_status import (
    DHAN_ORDER_STATUS_MAP, TERMINAL_STATUSES, is_terminal, normalize_status,
)

def test_status_table_values():
    assert DHAN_ORDER_STATUS_MAP["TRADED"] is OrderStatus.FILLED
    assert DHAN_ORDER_STATUS_MAP["FILLED"] is OrderStatus.FILLED
    assert DHAN_ORDER_STATUS_MAP["PART_TRADED"] is OrderStatus.OPEN
    assert DHAN_ORDER_STATUS_MAP["PARTIALLY_FILLED"] is OrderStatus.OPEN
    assert DHAN_ORDER_STATUS_MAP["TRANSIT"] is OrderStatus.PENDING
    assert DHAN_ORDER_STATUS_MAP["EXPIRED"] is OrderStatus.CANCELLED

def test_normalize_status_rules():
    assert normalize_status("traded") is OrderStatus.FILLED
    assert normalize_status("  part_traded ") is OrderStatus.OPEN
    assert normalize_status("WEIRD_NEW_CODE") is OrderStatus.PENDING
    assert normalize_status("") is OrderStatus.PENDING

def test_terminal_sets():
    assert is_terminal(OrderStatus.FILLED) is True
    assert is_terminal(OrderStatus.CANCELLED) is True
    assert is_terminal(OrderStatus.REJECTED) is True
    assert is_terminal(OrderStatus.PENDING) is False
    assert is_terminal(OrderStatus.OPEN) is False
    assert TERMINAL_STATUSES == frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED})
