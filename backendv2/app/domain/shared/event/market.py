"""Market data events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key


@dataclass(frozen=True)
class TickReceived(DomainEvent):
    """A new market tick arrived for a symbol.

    This is the foundational event — all market data flows from here.
    Published by the market data adapter, consumed by the session orchestrator.
    """

    symbol: str = ""
    price: float = 0.0
    volume: float = 0.0
    timestamp_ms: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    open_interest: float = 0.0

    def __str__(self) -> str:
        return f"TickReceived(symbol={self.symbol}, price={self.price})"


@dataclass(frozen=True)
class OrderBookSnapshot(DomainEvent):
    """A full order book snapshot was received."""

    symbol: str = ""
    bids: tuple = field(default_factory=tuple)  # ((price, qty), ...)
    asks: tuple = field(default_factory=tuple)
    timestamp_ms: float = 0.0
