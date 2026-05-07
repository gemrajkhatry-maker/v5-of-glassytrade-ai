"""Delta and Footprint events and data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


class TradeSide(Enum):
    """Trade side classification."""
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class DeltaType(Enum):
    """Type of delta event."""
    TRADE = "trade"
    CUMULATIVE = "cumulative"
    FOOTPRINT = "footprint"
    IMBALANCE = "imbalance"
    AUCTION = "auction"


@dataclass(frozen=True)
class TradeEvent:
    """Individual trade with delta classification."""
    timestamp: datetime
    price: float
    quantity: float
    side: TradeSide
    security_id: str
    is_aggressive_buyer: bool = False
    is_aggressive_seller: bool = False

    @property
    def delta(self) -> float:
        """Trade delta: positive for buys, negative for sells."""
        if self.side == TradeSide.BUY:
            return self.quantity
        elif self.side == TradeSide.SELL:
            return -self.quantity
        return 0.0


@dataclass(frozen=True)
class DeltaCandle:
    """Delta-aggregated candle."""
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    buy_volume: float
    sell_volume: float
    delta: float
    cumulative_delta: float = 0.0

    @property
    def delta_percentage(self) -> float:
        """Delta as percentage of total volume."""
        if self.volume == 0:
            return 0.0
        return (self.delta / self.volume) * 100.0


@dataclass(frozen=True)
class FootprintLevel:
    """Footprint data at single price level."""
    price: float
    bid_volume: float
    ask_volume: float
    delta: float
    imbalance_ratio: float = 0.0


@dataclass(frozen=True)
class FootprintCandle:
    """Footprint candle with price levels."""
    timestamp: datetime
    levels: List[FootprintLevel]
    total_volume: float
    total_delta: float
    poc_price: float = 0.0  # Point of Control

    @property
    def level_count(self) -> int:
        return len(self.levels)


@dataclass(frozen=True)
class ImbalanceEvent:
    """Volume imbalance event."""
    timestamp: datetime
    price: float
    bid_volume: float
    ask_volume: float
    imbalance_ratio: float
    is_stacked: bool = False
    consecutive_count: int = 1


@dataclass(frozen=True)
class AuctionEvent:
    """Auction analysis event."""
    timestamp: datetime
    price: float
    is_unfinished_auction: bool
    absorption_volume: float
    rejection_wick: float
    completion_ratio: float


@dataclass(frozen=True)
class DeltaEvent:
    """Generic delta event."""
    event_type: DeltaType
    timestamp: datetime
    symbol: str
    data: Dict = field(default_factory=dict)
