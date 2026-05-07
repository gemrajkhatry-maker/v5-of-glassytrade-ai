"""
Market data domain models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


@dataclass(frozen=True)
class Tick:
    """Immutable tick - the smallest market data unit."""
    instrument: "CanonicalInstrument"
    price: Decimal
    volume: int
    timestamp: datetime = field(default_factory=datetime.now)
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    sequence: Optional[int] = None
    
    def __hash__(self) -> int:
        """Make hashable for deduplication."""
        return hash((self.instrument.internal_uid, self.timestamp, self.price))


@dataclass(frozen=True)
class Quote:
    """Quote with bid/ask and OHLC."""
    instrument: "CanonicalInstrument"
    ltp: Decimal
    bid: Decimal
    ask: Decimal
    volume: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    timestamp: datetime = field(default_factory=datetime.now)
    oi: Optional[int] = None
    
    @property
    def spread(self) -> Decimal:
        """Bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def spread_pct(self) -> Optional[Decimal]:
        """Spread as percentage of LTP."""
        if self.ltp > 0:
            return (self.spread / self.ltp) * 100
        return None


@dataclass(frozen=True)
class DepthLevel:
    """Single level of market depth."""
    price: Decimal
    quantity: Decimal
    orders: Optional[int] = None


@dataclass(frozen=True)
class MarketDepth:
    """20-level market depth."""
    instrument: "CanonicalInstrument"
    bids: tuple  # Tuple of DepthLevel for stability
    asks: tuple
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __hash__(self) -> int:
        """Make hashable for deduplication."""
        return hash((self.instrument.internal_uid, self.timestamp))


@dataclass(frozen=True)
class Candle:
    """OHLCV candle."""
    instrument: "CanonicalInstrument"
    timeframe: str  # e.g., "1m", "5m", "1h", "1d"
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    
    @property
    def vwap(self) -> Optional[Decimal]:
        """Volume-weighted average price."""
        if self.volume > 0:
            # Simplified VWAP (typical price * volume / volume)
            typical = (self.high + self.low + self.close) / 3
            return typical  # In real implementation, use volume-weighted calculation
        return None


@dataclass
class FullPacket:
    """Full WebSocket packet from Dhan."""
    security_id: str
    symbol: str
    ltp: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: int
    atp: Decimal
    total_buy_qty: int
    total_sell_qty: int
    depth_bids: tuple
    depth_asks: tuple
    exchange_segment: str
    timestamp: datetime = field(default_factory=datetime.now)