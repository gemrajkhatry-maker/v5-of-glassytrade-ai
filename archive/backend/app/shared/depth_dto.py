"""Shared DTO conversion utilities.

Centralised pure functions for converting domain models → dicts
for serialization.  Used by both the engine and the WS layer to avoid
code duplication.
"""

from __future__ import annotations

# Module-level cache for depth DTOs
_depth_cache: dict[str, tuple[int, dict | None]] = {}


def order_book_to_dto(book: "OrderBook | None", symbol: str = "", max_levels: int = 20) -> dict | None:
    """Convert an ``OrderBook`` to a plain dict for JSON serialization.

    Caps bids/asks at *max_levels* to keep payloads bounded.
    Caches result per symbol; only recomputes when depth hash changes.
    """
    if not book:
        if symbol:
            _depth_cache.pop(symbol, None)
        return None

    # Quick hash of depth to detect changes
    depth_hash = hash((
        tuple((l.price, l.quantity) for l in book.bids[:max_levels]),
        tuple((l.price, l.quantity) for l in book.asks[:max_levels]),
    ))

    cached = _depth_cache.get(symbol)
    if cached and cached[0] == depth_hash:
        return cached[1]

    result = {
        "bids": [
            {"price": float(l.price), "quantity": float(l.quantity)}
            for l in book.bids[:max_levels]
        ],
        "asks": [
            {"price": float(l.price), "quantity": float(l.quantity)}
            for l in book.asks[:max_levels]
        ],
    }
    if symbol:
        _depth_cache[symbol] = (depth_hash, result)
    return result
