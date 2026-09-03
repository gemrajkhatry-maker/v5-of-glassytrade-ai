"""Sole Dhan order-status vocabulary. (REF-06)

Unknown strings default to PENDING (never guess terminal — a wrong terminal
guess would drop a live order). Terminal = FILLED | CANCELLED | REJECTED.
"""
from __future__ import annotations

from brokers.broker.types import OrderStatus

__all__ = [
    "DHAN_ORDER_STATUS_MAP",
    "TERMINAL_STATUSES",
    "is_terminal",
    "normalize_status",
]

DHAN_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "PENDING": OrderStatus.PENDING,
    "TRANSIT": OrderStatus.PENDING,
    "OPEN": OrderStatus.OPEN,
    "PARTIALLY_FILLED": OrderStatus.OPEN,
    "PART_TRADED": OrderStatus.OPEN,
    "TRADED": OrderStatus.FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "CANCELED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.CANCELLED,
}

TERMINAL_STATUSES: frozenset = frozenset({
    OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
})


def normalize_status(raw: object) -> OrderStatus:
    """Map a raw Dhan status string to OrderStatus (strip/upper, unknown→PENDING)."""
    key = str(raw or "").strip().upper()
    return DHAN_ORDER_STATUS_MAP.get(key, OrderStatus.PENDING)


def is_terminal(status: OrderStatus) -> bool:
    """True when no further updates are expected for this status."""
    return status in TERMINAL_STATUSES
