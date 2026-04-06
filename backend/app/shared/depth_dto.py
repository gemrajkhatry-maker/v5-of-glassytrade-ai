"""Shared DTO conversion utilities.

Centralised pure functions for converting domain models → dicts
for serialization.  Used by both the engine and the WS layer to avoid
code duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OrderBook


def order_book_to_dto(book: "OrderBook | None", max_levels: int = 20) -> dict | None:
    """Convert an ``OrderBook`` to a plain dict for JSON serialization.

    Caps bids/asks at *max_levels* to keep payloads bounded.
    """
    if not book:
        return None
    return {
        "bids": [
            {"price": float(l.price), "quantity": float(l.quantity)}
            for l in book.bids[:max_levels]
        ],
        "asks": [
            {"price": float(l.price), "quantity": float(l.quantity)}
            for l in book.asks[:max_levels]
        ],
    }
