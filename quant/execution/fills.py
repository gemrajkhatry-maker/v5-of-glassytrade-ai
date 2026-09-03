"""Sole broker-fill mapping. (REF-06)

Every ``getattr(broker_pos, ...)`` chain in LiveOMS routes through
:func:`broker_position_to_fill` so fallback semantics (and their audit
marker) live in exactly one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["BrokerFill", "broker_position_to_fill"]


@dataclass(frozen=True)
class BrokerFill:
    fill_price: float
    filled_qty: float
    fill_quantity_assumed: bool = False


def broker_position_to_fill(
    broker_pos: Any, *, fallback_price: float, fallback_qty: float,
) -> BrokerFill:
    """Map a broker Position-like onto floats, marking fallback use."""
    raw_price = getattr(broker_pos, "entry_price", None)
    raw_size = getattr(broker_pos, "size", None)
    assumed = raw_price is None or raw_size is None
    try:
        price = float(raw_price) if raw_price is not None else fallback_price
    except (TypeError, ValueError):
        price, assumed = fallback_price, True
    try:
        qty = float(raw_size) if raw_size is not None else fallback_qty
    except (TypeError, ValueError):
        qty, assumed = fallback_qty, True
    return BrokerFill(fill_price=price, filled_qty=qty, fill_quantity_assumed=assumed)
