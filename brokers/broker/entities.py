"""
Broker Entities - Domain entities for broker operations.

These entities are immutable value objects representing market data and orders.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Iterator

import pandas as pd

from .types import Exchange, OptionType, OrderSide, OrderType, OrderStatus


@dataclass(frozen=True)
class Instrument:
    """
    Immutable instrument representation.

    Represents a tradeable instrument (stock, option, futures, etc.)

    Note:
        security_id is an internal broker implementation detail.
        Callers should use human-readable symbol names; the broker
        resolves security_id internally.
    """

    symbol: str
    exchange: Exchange
    security_id: str = ""
    option_type: Optional[OptionType] = None
    strike: Optional[float] = None
    expiry: Optional[datetime] = None

    def is_option(self) -> bool:
        """Check if instrument is an option."""
        return self.option_type is not None

    def is_index(self) -> bool:
        """Check if instrument is an index."""
        return self.exchange == Exchange.INDEX


@dataclass(frozen=True)
class DepthLevel:
    """
    Single level of market depth.

    Attributes:
        price: Price at this level
        quantity: Total quantity at this level
        orders: Number of orders (optional, for 20-level depth)
    """

    price: float
    quantity: int
    orders: Optional[int] = None

    def __str__(self) -> str:
        if self.orders:
            return f"₹{self.price:.2f} × {self.quantity} ({self.orders} orders)"
        return f"₹{self.price:.2f} × {self.quantity}"


@dataclass
class Quote:
    """
    Market quote data with optional depth.

    Supports both basic quotes and full quotes with market depth.
    """

    instrument: Instrument
    ltp: float
    bid: float
    ask: float
    volume: int
    open: float
    high: float
    low: float
    close: float
    timestamp: datetime = field(default_factory=datetime.now)
    # Open interest (for derivatives; optional)
    oi: Optional[int] = None
    # Optional depth data
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
    """
    Single price update.

    `bid`, `ask`, `bid_depth`, `ask_depth` are optional so existing
    callers constructing `Tick(instrument=..., price=..., volume=..., timestamp=...)`
    continue to work unchanged.  Live feeds populate bid/ask when the broker
    provides them (e.g. Dhan Quote feed).  Depth lists use the same
    `DepthLevel` type used by `Quote`.
    """

    instrument: Instrument
    price: float
    volume: int
    timestamp: datetime = field(default_factory=datetime.now)
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_depth: Optional[List[DepthLevel]] = None
    ask_depth: Optional[List[DepthLevel]] = None


@dataclass
class Order:
    """
    Order representation.

    New fields (`trigger_price`, `product_type`) default to safe values so
    all existing constructors continue to work without modification.

    `trigger_price` is the stop-loss activation price required for SL and
    SLM order types.  `product_type` maps to Dhan's productType field:
    INTRADAY, CNC, MARGIN, CO, BO.
    """

    instrument: Instrument
    side: OrderSide
    quantity: float
    price: Optional[float] = None
    order_id: str = ""
    order_type: OrderType = OrderType.MARKET
    trigger_price: Optional[float] = None   # SL / SLM activation price
    product_type: str = "INTRADAY"          # INTRADAY | CNC | MARGIN | CO | BO
    filled_quantity: float = 0
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """Portfolio position."""

    instrument: Instrument
    quantity: float
    avg_price: float
    unrealized_pnl: float = 0
    realized_pnl: float = 0


@dataclass(frozen=True)
class Option:
    """
    Single option contract with full market data.

    Includes Greeks, OHLC, OI, volume, and spread information.
    Immutable for thread safety.
    """

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
    bid_qty: Optional[int] = None   # top_bid_quantity from API
    ask_qty: Optional[int] = None   # top_ask_quantity from API
    # Prior-day data
    prev_oi: Optional[int] = None       # previous_oi  — OI change analysis
    prev_volume: Optional[int] = None   # previous_volume
    avg_price: Optional[float] = None   # average_price (day VWAP-like)
    # Greeks
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    # OHLC
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    prev_close: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        """Spread as percentage of LTP."""
        if self.spread is not None and self.ltp > 0:
            return (self.spread / self.ltp) * 100
        return None

    @property
    def is_call(self) -> bool:
        """Check if this is a call option."""
        return self.option_type.upper() == "CE"

    @property
    def is_put(self) -> bool:
        """Check if this is a put option."""
        return self.option_type.upper() == "PE"


@dataclass
class OptionChain:
    """
    Full option chain for an underlying instrument.

    Contains all available strikes for a specific expiry,
    organized into calls and puts dictionaries keyed by strike price.
    """

    underlying: Instrument
    expiry: datetime
    spot_price: float
    atm_strike: float
    step_size: float
    calls: Dict[float, Option] = field(default_factory=dict)
    puts: Dict[float, Option] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Enforce type safety for numeric fields."""
        # Ensure spot_price is float
        if not isinstance(self.spot_price, (int, float)):
            object.__setattr__(
                self,
                "spot_price",
                float(self.spot_price) if self.spot_price is not None else 0.0,
            )
        # Ensure atm_strike is float
        if not isinstance(self.atm_strike, (int, float)):
            object.__setattr__(
                self,
                "atm_strike",
                float(self.atm_strike) if self.atm_strike is not None else 0.0,
            )
        # Ensure step_size is float
        if not isinstance(self.step_size, (int, float)):
            object.__setattr__(
                self,
                "step_size",
                float(self.step_size) if self.step_size is not None else 100.0,
            )

    @property
    def strikes(self) -> List[float]:
        """All available strikes, sorted."""
        all_strikes = set(self.calls.keys()) | set(self.puts.keys())
        return sorted(all_strikes)

    def get_atm_options(self) -> Tuple[Optional[Option], Optional[Option]]:
        """Get ATM call and put options."""
        atm_ce = self.calls.get(self.atm_strike)
        atm_pe = self.puts.get(self.atm_strike)
        return atm_ce, atm_pe

    def get_option(self, strike: float, option_type: str) -> Optional[Option]:
        """Get specific option by strike and type ('CE' or 'PE')."""
        if option_type.upper() == "CE":
            return self.calls.get(strike)
        elif option_type.upper() == "PE":
            return self.puts.get(strike)
        return None

    def get_strikes_around(self, offset: int = 3) -> List[float]:
        """Get strikes around ATM."""
        strikes = []
        for i in range(-offset, offset + 1):
            strike = self.atm_strike + (i * self.step_size)
            # Check both float and int representations
            if (
                strike in self.calls
                or strike in self.puts
                or int(strike) in self.calls
                or int(strike) in self.puts
            ):
                strikes.append(strike)
        return sorted(strikes)

    def get_options_around(self, offset: int = 3) -> List[Option]:
        """Get all options (CE and PE) around ATM strike."""
        strikes = self.get_strikes_around(offset)
        options = []
        for strike in strikes:
            # Try both float and int keys
            call = self.calls.get(strike) or self.calls.get(int(strike))
            put = self.puts.get(strike) or self.puts.get(int(strike))
            if call:
                options.append(call)
            if put:
                options.append(put)
        return options

    def get_otm_options(
        self, distance: int = 1
    ) -> Tuple[Optional[Option], Optional[Option]]:
        """
        Get OTM call and put options.
        OTM Call = ATM + (distance * step_size)
        OTM Put = ATM - (distance * step_size)
        """
        ce_strike = self.atm_strike + (distance * self.step_size)
        pe_strike = self.atm_strike - (distance * self.step_size)

        otm_ce = self.calls.get(ce_strike)
        otm_pe = self.puts.get(pe_strike)
        return otm_ce, otm_pe

    def get_itm_options(
        self, distance: int = 1
    ) -> Tuple[Optional[Option], Optional[Option]]:
        """
        Get ITM call and put options.
        ITM Call = ATM - (distance * step_size)
        ITM Put = ATM + (distance * step_size)
        """
        ce_strike = self.atm_strike - (distance * self.step_size)
        pe_strike = self.atm_strike + (distance * self.step_size)

        itm_ce = self.calls.get(ce_strike)
        itm_pe = self.puts.get(pe_strike)
        return itm_ce, itm_pe


@dataclass(frozen=True)
class FullPacket:
    """
    Typed representation of a FULL WebSocket packet (feed_type=21).

    Contains tick-level LTP, OHLC, volume, OI, and 5-level depth.
    Works for all exchange segments including MCX.

    Fields:
        symbol: Human-readable trading symbol (e.g. "CRUDEOIL 17 MAR 6050 CALL")
        ltp: Last traded price
        open/high/low/close: Session OHLC
        volume: Cumulative daily volume
        oi: Open interest (derivatives only, 0 for equities)
        atp: Average traded price (day VWAP)
        total_buy_qty: Total bid quantity across all levels
        total_sell_qty: Total ask quantity across all levels
        depth_bids: 5-level bid depth (price, qty)
        depth_asks: 5-level ask depth (price, qty)
        security_id: Dhan internal security ID
        exchange_segment: Segment string (e.g. "NSE_EQ", "MCX_COMM")
        timestamp: Server timestamp (IST datetime)
    """

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
    ltq: int = 0          # Last traded quantity
    ltt: int = 0          # Last trade time (epoch seconds)


@dataclass(frozen=True)
class MarketDepth:
    """
    20-level market depth (orderbook).

    Attributes:
        symbol: Trading symbol
        security_id: DhanHQ security ID
        side: Bid or Ask side
        levels: List of depth levels (up to 20)
        timestamp: Depth snapshot timestamp
    """

    symbol: str
    security_id: str
    side: str  # "bid" or "ask"
    levels: List[DepthLevel]
    timestamp: datetime

    @property
    def best_level(self) -> Optional[DepthLevel]:
        """Returns best price level (L1)."""
        return self.levels[0] if self.levels else None

    @property
    def total_quantity(self) -> int:
        """Returns total quantity across all levels."""
        return sum(level.quantity for level in self.levels)

    @property
    def total_orders(self) -> Optional[int]:
        """Returns total orders if available."""
        if self.levels and self.levels[0].orders is not None:
            return sum(level.orders for level in self.levels if level.orders)
        return None

    def __str__(self) -> str:
        best = self.best_level
        if best:
            return f"{self.symbol} {self.side}: {len(self.levels)} levels, Best: {best}"
        return f"{self.symbol} {self.side}: {len(self.levels)} levels"


@dataclass
class BulkHistoricalResult:
    """
    Result of bulk historical data download.
    """

    data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def successful(self) -> int:
        return len(self.data)

    @property
    def failed(self) -> int:
        return len(self.errors)

    @property
    def total(self) -> int:
        return self.successful + self.failed

    def __getitem__(self, symbol: str) -> pd.DataFrame:
        return self.data[symbol]

    def get(self, symbol: str) -> Optional[pd.DataFrame]:
        return self.data.get(symbol)

    def __iter__(self) -> Iterator[pd.DataFrame]:
        return iter(self.data.values())
