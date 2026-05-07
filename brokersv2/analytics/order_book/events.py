"""Order book events and data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class OrderBookEventType(Enum):
    """Types of order book events."""
    SNAPSHOT = "snapshot"
    BID_UPDATE = "bid_update"
    ASK_UPDATE = "ask_update"
    TRADE = "trade"
    SWEEP = "sweep"
    IMBALANCE = "imbalance"


@dataclass(frozen=True)
class PriceLevel:
    """Immutable price level in order book."""
    price: float
    quantity: float
    order_count: int = 1

    @property
    def notional(self) -> float:
        """Total notional value at this level."""
        return self.price * self.quantity


@dataclass(frozen=True)
class OrderBookSnapshot:
    """Complete order book snapshot."""
    symbol: str
    timestamp: datetime
    bids: List[PriceLevel]
    asks: List[PriceLevel]
    sequence: int = 0

    @property
    def bid_levels(self) -> int:
        return len(self.bids)

    @property
    def ask_levels(self) -> int:
        return len(self.asks)

    @property
    def best_bid(self) -> Optional[PriceLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[PriceLevel]:
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2.0
        return None


@dataclass(frozen=True)
class OrderBookEvent:
    """Immutable order book event."""
    event_type: OrderBookEventType
    symbol: str
    timestamp: datetime
    sequence: int
    snapshot: Optional[OrderBookSnapshot] = None
    updated_levels: Optional[List[PriceLevel]] = None
    metadata: Dict = field(default_factory=dict)

    @property
    def is_snapshot(self) -> bool:
        return self.event_type == OrderBookEventType.SNAPSHOT

    @property
    def is_bid_update(self) -> bool:
        return self.event_type == OrderBookEventType.BID_UPDATE

    @property
    def is_ask_update(self) -> bool:
        return self.event_type == OrderBookEventType.ASK_UPDATE
