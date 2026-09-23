"""
Canonical domain entities for GlassyTrade AI.
Shared across backend (domain) and brokers (infrastructure).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any
import uuid

# =============================================================================
# Core Enums (Consolidated)
# =============================================================================

class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    INDEX = "INDEX"

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    # Aliases for domain Side compatibility
    LONG = "BUY"
    SHORT = "SELL"

Side = OrderSide

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SLM = "SLM"

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"    # For position lifecycle

class OptionType(str, Enum):
    CALL = "CE"
    PUT = "PE"

class SessionPhase(str, Enum):
    OPENING = "Phase 1: Opening Noise (High Risk)"
    PRIMARY = "Phase 2: Primary Setup Window (AAA)"
    MIDDAY = "Phase 3: Midday Consolidation (Reversion Only)"
    POWER_HOUR = "Phase 4: Power Hour (High Volatility)"
    CLOSE_PROTECTION = "Phase 5: Close Protection (Exit Only)"
    OUTSIDE_HOURS = "Outside Market Hours"

# =============================================================================
# Value Objects
# =============================================================================

@dataclass(frozen=True)
class Instrument:
    symbol: str
    exchange: Exchange
    security_id: str = ""
    option_type: Optional[OptionType] = None
    strike: Optional[float] = None
    expiry: Optional[datetime] = None

    def is_option(self) -> bool:
        return self.option_type is not None

    def is_index(self) -> bool:
        return self.exchange == Exchange.INDEX

# =============================================================================
# Market Data
# =============================================================================

@dataclass
class Quote:
    instrument: Instrument
    ltp: float
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    oi: Optional[int] = None
    bid_depth: Optional[List[DepthLevel]] = None
    ask_depth: Optional[List[DepthLevel]] = None

    @property
    def has_depth(self) -> bool:
        """Returns True if depth data is available."""
        return self.bid_depth is not None or self.ask_depth is not None

    @property
    def spread(self) -> Optional[float]:
        """Returns bid-ask spread if available."""
        if self.bid and self.ask:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        """Returns spread as percentage of LTP."""
        spread = self.spread
        if spread and self.ltp:
            return (spread / self.ltp) * 100
        return None

@dataclass
class Tick:
    instrument: Instrument
    price: float
    volume: int
    timestamp: datetime = field(default_factory=datetime.now)
    bid: Optional[float] = None
    ask: Optional[float] = None

# =============================================================================
# Trading Entities
# =============================================================================

@dataclass
class Order:
    instrument: Instrument
    side: OrderSide
    quantity: float
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    product_type: str = "INTRADAY"
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_type: OrderType = OrderType.MARKET
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = field(default_factory=datetime.now)
    filled_quantity: float = 0
    average_fill_price: Optional[float] = None
    fills: List[dict] = field(default_factory=list)
    commission: float = 0.0

@dataclass(frozen=True)
class DepthLevel:
    """Single level of market depth."""
    price: float
    quantity: int
    orders: Optional[int] = None

    def __str__(self) -> str:
        if self.orders:
            return f"₹{self.price:.2f} × {self.quantity} ({self.orders} orders)"
        return f"₹{self.price:.2f} × {self.quantity}"

@dataclass(frozen=True)
class Option:
    """Single option contract with market data."""
    symbol: str
    security_id: str
    strike: float
    option_type: str  # 'CE' or 'PE'
    expiry: datetime
    ltp: float
    oi: int = 0
    volume: int = 0
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_qty: Optional[int] = None
    ask_qty: Optional[int] = None
    prev_oi: Optional[int] = None
    prev_volume: Optional[int] = None
    avg_price: Optional[float] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    prev_close: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_call(self) -> bool:
        return self.option_type.upper() == "CE"

    @property
    def is_put(self) -> bool:
        return self.option_type.upper() == "PE"

@dataclass
class OptionChain:
    """Full option chain for an underlying."""
    underlying: Instrument
    expiry: datetime
    spot_price: float
    atm_strike: float
    step_size: float
    calls: Dict[float, Option] = field(default_factory=dict)
    puts: Dict[float, Option] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def strikes(self) -> List[float]:
        """Returns a sorted list of all unique strikes in the chain."""
        return sorted(list(set(self.calls.keys()) | set(self.puts.keys())))

@dataclass(frozen=True)
class FullPacket:
    """Full WebSocket packet (feed_type=21)."""
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int
    atp: float
    total_buy_qty: int
    total_sell_qty: int
    depth_bids: tuple
    depth_asks: tuple
    security_id: str
    exchange_segment: str
    timestamp: datetime
    ltq: int = 0
    ltt: int = 0

@dataclass(frozen=True)
class MarketDepth:
    """20-level market depth snapshots."""
    symbol: str
    security_id: str
    side: str
    levels: List[DepthLevel]
    timestamp: datetime

@dataclass
class BulkHistoricalResult:
    """Result of bulk historical data download."""
    data: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)

@dataclass
class Position:
    instrument: Instrument
    side: OrderSide = OrderSide.BUY
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: OrderStatus = OrderStatus.OPEN
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs):
        # Backward compatibility for 'avg_price' (Dhan API shape mapping)
        if 'avg_price' in kwargs and 'entry_price' not in kwargs:
            kwargs['entry_price'] = kwargs.pop('avg_price')
        
        for key, value in kwargs.items():
            setattr(self, key, value)
        
        if not hasattr(self, 'side'):
            self.side = OrderSide.BUY
        if not hasattr(self, 'id'):
            self.id = str(uuid.uuid4())
        if not hasattr(self, 'entry_time'):
            self.entry_time = datetime.now()
        if not hasattr(self, 'status'):
            self.status = OrderStatus.OPEN

    @property
    def avg_price(self) -> float:
        return self.entry_price

    @avg_price.setter
    def avg_price(self, value: float):
        self.entry_price = value

    @property
    def is_open(self) -> bool:
        return self.status == OrderStatus.OPEN
