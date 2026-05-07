"""
Market Data Events - Immutable typed models for market microstructure.

Uses msgspec for zero-copy deserialization and maximum performance.
All events are immutable and frozen for thread safety.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import msgspec


# =============================================================================
# Exchange & Instrument Types
# =============================================================================

class Exchange(str, Enum):
    """Supported exchanges."""
    NSE = "NSE"
    NFO = "NFO"  # NSE F&O
    BSE = "BSE"
    BFO = "BFO"  # BSE F&O
    MCX = "MCX"
    CDS = "CDS"  # Currency


class InstrumentType(str, Enum):
    """Instrument types."""
    EQUITY = "EQ"
    FUTURES = "FUT"
    OPTIONS = "OPT"
    INDEX = "IDX"


class OptionType(str, Enum):
    """Option types."""
    CALL = "CE"
    PUT = "PE"


# =============================================================================
# Market Data Events (Immutable)
# =============================================================================

@dataclass(frozen=True)
class TickEvent:
    """
    Level 1 market data event - single tick.
    
    Immutable, thread-safe, replay-compatible.
    """
    timestamp: datetime
    security_id: str
    symbol: str
    exchange: Exchange
    
    # Price data
    ltp: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    
    # Volume & OI
    volume: int
    oi: int = 0
    
    # Derived metrics
    vwap: Optional[Decimal] = None
    atp: Optional[Decimal] = None  # Average traded price
    
    # Metadata
    sequence: int = 0
    is_delayed: bool = False
    
    @property
    def change(self) -> Decimal:
        """Price change from previous close."""
        return self.ltp - self.close
    
    @property
    def change_pct(self) -> Decimal:
        """Percentage change from previous close."""
        if self.close == 0:
            return Decimal("0")
        return (self.change / self.close) * Decimal("100")


@dataclass(frozen=True)
class DepthLevel:
    """Single depth level (bid or ask)."""
    price: Decimal
    quantity: int
    orders: int = 0  # Number of orders at this level


@dataclass(frozen=True)
class DepthEvent:
    """
    Level 2 market data event - full market depth.
    
    Supports up to 20 levels (DhanHQ max).
    Immutable, thread-safe, replay-compatible.
    """
    timestamp: datetime
    security_id: str
    symbol: str
    exchange: Exchange
    
    # Depth ladders
    bids: tuple[DepthLevel, ...]  # Sorted best-to-worst
    asks: tuple[DepthLevel, ...]  # Sorted best-to-worst
    
    # Metadata
    sequence: int = 0
    is_snapshot: bool = True  # True = full snapshot, False = incremental update
    
    @property
    def best_bid(self) -> Optional[DepthLevel]:
        """Best bid price."""
        return self.bids[0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[DepthLevel]:
        """Best ask price."""
        return self.asks[0] if self.asks else None
    
    @property
    def spread(self) -> Optional[Decimal]:
        """Bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None
    
    @property
    def mid_price(self) -> Optional[Decimal]:
        """Mid price."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None
    
    @property
    def bid_volume(self) -> int:
        """Total bid volume."""
        return sum(level.quantity for level in self.bids)
    
    @property
    def ask_volume(self) -> int:
        """Total ask volume."""
        return sum(level.quantity for level in self.asks)
    
    @property
    def imbalance(self) -> float:
        """
        Order book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
        Range: [-1, 1]
        Positive = buying pressure, Negative = selling pressure
        """
        total = self.bid_volume + self.ask_volume
        if total == 0:
            return 0.0
        return (self.bid_volume - self.ask_volume) / total


@dataclass(frozen=True)
class QuoteEvent:
    """
    Market quote event - 52-week range, upper/lower circuits.
    """
    timestamp: datetime
    security_id: str
    symbol: str
    exchange: Exchange
    
    # Quote data
    ltp: Decimal
    close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    
    # Range data
    high_52w: Optional[Decimal] = None
    low_52w: Optional[Decimal] = None
    
    # Circuit limits
    upper_circuit: Optional[Decimal] = None
    lower_circuit: Optional[Decimal] = None
    
    # Volume
    volume: int = 0
    value: Decimal = Decimal("0")  # Total traded value


@dataclass(frozen=True)
class CandleEvent:
    """
    OHLC candle event - aggregated from ticks.
    """
    timestamp: datetime
    security_id: str
    symbol: str
    exchange: Exchange
    
    # Candle data
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: int = 0
    
    # Timeframe
    timeframe: str = "1m"  # 1m, 5m, 15m, 1h, 1d
    
    # Derived
    vwap: Optional[Decimal] = None
    trades: int = 0  # Number of trades in candle


# =============================================================================
# Encoder/Decoder for serialization
# =============================================================================

class MarketDataCodec:
    """
    High-performance msgspec encoder/decoder for market data events.
    
    Provides:
    - Fast serialization to bytes
    - Fast deserialization from bytes
    - Replay-compatible binary format
    """
    
    def __init__(self):
        self._encoder = msgspec.json.Encoder()
        self._tick_decoder = msgspec.json.Decoder(TickEvent)
        self._depth_decoder = msgspec.json.Decoder(DepthEvent)
        self._quote_decoder = msgspec.json.Decoder(QuoteEvent)
        self._candle_decoder = msgspec.json.Decoder(CandleEvent)
    
    def encode_tick(self, event: TickEvent) -> bytes:
        """Encode TickEvent to bytes."""
        return self._encoder.encode(event)
    
    def decode_tick(self, data: bytes) -> TickEvent:
        """Decode TickEvent from bytes."""
        return self._tick_decoder.decode(data)
    
    def encode_depth(self, event: DepthEvent) -> bytes:
        """Encode DepthEvent to bytes."""
        return self._encoder.encode(event)
    
    def decode_depth(self, data: bytes) -> DepthEvent:
        """Decode DepthEvent from bytes."""
        return self._depth_decoder.decode(data)
    
    def encode_quote(self, event: QuoteEvent) -> bytes:
        """Encode QuoteEvent to bytes."""
        return self._encoder.encode(event)
    
    def decode_quote(self, data: bytes) -> QuoteEvent:
        """Decode QuoteEvent from bytes."""
        return self._quote_decoder.decode(data)
    
    def encode_candle(self, event: CandleEvent) -> bytes:
        """Encode CandleEvent to bytes."""
        return self._encoder.encode(event)
    
    def decode_candle(self, data: bytes) -> CandleEvent:
        """Decode CandleEvent from bytes."""
        return self._candle_decoder.decode(data)
