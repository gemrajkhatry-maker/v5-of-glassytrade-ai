"""
Dhan Domain Value Objects - Immutable value objects for Dhan broker.

This module defines value objects that represent concepts in the Dhan
domain. All value objects are immutable (frozen dataclasses or enums).

No external dependencies except standard library.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from brokers.broker.types import Exchange

from .constants import (
    NSE_CASH,
    NSE_FNO,
    NSE_CURRENCY,
    BSE_CASH,
    MCX,
    BSE_FNO,
    IDX_I,
    EQUITY,
    FUTURES,
    OPTIONS,
    CURRENCY,
    COMMODITY,
    FEED_TYPE_TICKER,
    FEED_TYPE_QUOTE,
    FEED_TYPE_FULL,
    FEED_TYPE_FULL_DEPTH,
)


# =============================================================================
# Enums
# =============================================================================


class InstrumentTypeEnum(str, Enum):
    """
    Dhan instrument types.

    These are the instrument type codes used by the Dhan API
    to identify different types of tradeable instruments.
    """

    EQUITY = "EQ"
    INDEX = "INDEX"
    INDEX_FUTURE = "FUTIDX"
    STOCK_FUTURE = "FUTSTK"
    INDEX_OPTION = "OPTIDX"
    STOCK_OPTION = "OPTSTK"
    COMMODITY_FUTURE = "FUTCOM"
    COMMODITY_OPTION = "OPTFUT"
    CURRENCY_FUTURE = "FUTCUR"
    CURRENCY_OPTION = "OPTCUR"

    @property
    def is_future(self) -> bool:
        """Check if this instrument type is a future."""
        return self in (
            InstrumentTypeEnum.INDEX_FUTURE,
            InstrumentTypeEnum.STOCK_FUTURE,
            InstrumentTypeEnum.COMMODITY_FUTURE,
            InstrumentTypeEnum.CURRENCY_FUTURE,
        )

    @property
    def is_option(self) -> bool:
        """Check if this instrument type is an option."""
        return self in (
            InstrumentTypeEnum.INDEX_OPTION,
            InstrumentTypeEnum.STOCK_OPTION,
            InstrumentTypeEnum.COMMODITY_OPTION,
            InstrumentTypeEnum.CURRENCY_OPTION,
        )

    @property
    def is_equity(self) -> bool:
        """Check if this instrument type is equity."""
        return self == InstrumentTypeEnum.EQUITY

    @property
    def is_index(self) -> bool:
        """Check if this instrument type is an index."""
        return self == InstrumentTypeEnum.INDEX


class FeedType(str, Enum):
    """
    WebSocket feed types.

    These are the feed type codes used when subscribing to
    WebSocket market data streams.
    """

    TICKER = "TICKER"  # LTP only (code 15)
    QUOTE = "QUOTE"  # LTP + OHLC + Volume (code 17)
    FULL = "FULL"  # Quote + 5-level depth (code 21)
    FULL_DEPTH = "FULL_DEPTH"  # 20-level depth (code 20)

    @property
    def code(self) -> int:
        """Get the Dhan API code for this feed type."""
        codes = {
            FeedType.TICKER: FEED_TYPE_TICKER,
            FeedType.QUOTE: FEED_TYPE_QUOTE,
            FeedType.FULL: FEED_TYPE_FULL,
            FeedType.FULL_DEPTH: FEED_TYPE_FULL_DEPTH,
        }
        return codes[self]


class ProductType(str, Enum):
    """
    Order product types.

    These are the product type codes used when placing orders.
    """

    INTRADAY = "I"  # Intraday / MIS
    MARGIN = "M"  # Margin / NRML
    CNC = "C"  # Cash and Carry
    COVER_ORDER = "CO"  # Cover Order
    BRACKET_ORDER = "BO"  # Bracket Order


class OrderValidity(str, Enum):
    """
    Order validity types.

    These define how long an order remains active.
    """

    DAY = "DAY"  # Valid for the trading day
    IOC = "IOC"  # Immediate or Cancel
    GTC = "GTC"  # Good Till Cancelled


class OptionType(str, Enum):
    """
    Option type (Call/Put).

    Dhan uses 'CE' for Call and 'PE' for Put options.
    """

    CALL = "CE"
    PUT = "PE"


# =============================================================================
# Value Objects (Frozen Dataclasses)
# =============================================================================


@dataclass(frozen=True)
class ExchangeSegment:
    """
    Dhan exchange segment with code mapping.

    Represents a trading segment on an exchange with its associated
    Dhan API code. This is used to identify the correct segment
    when making API calls.

    Attributes:
        name: Human-readable segment name (e.g., "NSE_EQ", "NSE_FNO").
        code: Dhan API code for this segment (e.g., 1, 2).

    Example:
        >>> segment = ExchangeSegment.NSE_FNO
        >>> segment.name
        'NSE_FNO'
        >>> segment.code
        2
    """

    name: str
    code: int

    # Predefined segments as class attributes
    NSE_EQ = None  # type: ExchangeSegment
    NSE_FNO = None  # type: ExchangeSegment
    NSE_CURRENCY = None  # type: ExchangeSegment
    BSE_EQ = None  # type: ExchangeSegment
    MCX = None  # type: ExchangeSegment
    BSE_FNO = None  # type: ExchangeSegment
    IDX_I = None  # type: ExchangeSegment

    @classmethod
    def from_code(cls, code: int) -> Optional["ExchangeSegment"]:
        """
        Get exchange segment from Dhan code.

        Args:
            code: The Dhan API code for the segment.

        Returns:
            The ExchangeSegment for the given code, or None if not found.
        """
        segments = {
            NSE_CASH: cls.NSE_EQ,
            NSE_FNO: cls.NSE_FNO,
            NSE_CURRENCY: cls.NSE_CURRENCY,
            BSE_CASH: cls.BSE_EQ,
            MCX: cls.MCX,
            BSE_FNO: cls.BSE_FNO,
            IDX_I: cls.IDX_I,
        }
        return segments.get(code)

    @classmethod
    def from_exchange_code(cls, exchange_code: str) -> Optional["ExchangeSegment"]:
        """
        Get exchange segment from exchange code string (used in CSV).

        Args:
            exchange_code: The exchange code string (e.g., "NSE", "BSE", "MCX").

        Returns:
            The ExchangeSegment for the given exchange code.
        """
        code_map = {
            "NSE": cls.NSE_FNO,
            "BSE": cls.BSE_FNO,
            "MCX": cls.MCX,
        }
        return code_map.get(exchange_code.upper())

    @classmethod
    def from_name(cls, name: str) -> Optional["ExchangeSegment"]:
        """
        Get exchange segment from name.

        Args:
            name: The segment name (e.g., "NSE_FNO").

        Returns:
            The ExchangeSegment for the given name, or None if not found.
        """
        segments = {
            "NSE_EQ": cls.NSE_EQ,
            "NSE_FNO": cls.NSE_FNO,
            "NSE_CURRENCY": cls.NSE_CURRENCY,
            "BSE_EQ": cls.BSE_EQ,
            "MCX": cls.MCX,
            "MCX_COMM": cls.MCX,
            "BSE_FNO": cls.BSE_FNO,
            "NSE_CASH": cls.NSE_EQ,
            "BSE_CASH": cls.BSE_EQ,
            "IDX_I": cls.IDX_I,
        }
        return segments.get(name.upper() if name else "")

    @property
    def is_equity(self) -> bool:
        """Check if this is an equity segment."""
        return self in (ExchangeSegment.NSE_EQ, ExchangeSegment.BSE_EQ)

    @property
    def is_derivatives(self) -> bool:
        """Check if this is a derivatives segment."""
        return self in (
            ExchangeSegment.NSE_FNO,
            ExchangeSegment.NSE_CURRENCY,
            ExchangeSegment.BSE_FNO,
            ExchangeSegment.MCX,
        )

    @property
    def is_commodity(self) -> bool:
        """Check if this is a commodity segment."""
        return self == ExchangeSegment.MCX

    def to_exchange(self) -> "Exchange":
        """
        Convert ExchangeSegment to Exchange enum.

        Returns:
            Exchange enum value.
        """
        from brokers.broker.types import Exchange

        segment_map = {
            ExchangeSegment.NSE_EQ: Exchange.NSE,
            ExchangeSegment.NSE_FNO: Exchange.NFO,
            ExchangeSegment.NSE_CURRENCY: Exchange.NFO,
            ExchangeSegment.BSE_EQ: Exchange.BSE,
            ExchangeSegment.BSE_FNO: Exchange.BFO,
            ExchangeSegment.MCX: Exchange.MCX,
        }
        return segment_map.get(self, Exchange.NSE)


# Initialize predefined segments
ExchangeSegment.NSE_EQ = ExchangeSegment(name="NSE_EQ", code=NSE_CASH)
ExchangeSegment.NSE_FNO = ExchangeSegment(name="NSE_FNO", code=NSE_FNO)
ExchangeSegment.NSE_CURRENCY = ExchangeSegment(name="NSE_CURRENCY", code=NSE_CURRENCY)
ExchangeSegment.BSE_EQ = ExchangeSegment(name="BSE_EQ", code=BSE_CASH)
ExchangeSegment.MCX = ExchangeSegment(name="MCX", code=MCX)
ExchangeSegment.BSE_FNO = ExchangeSegment(name="BSE_FNO", code=BSE_FNO)
ExchangeSegment.IDX_I = ExchangeSegment(name="IDX_I", code=IDX_I)


@dataclass(frozen=True)
class InstrumentTypeVO:
    """
    Dhan instrument type with code mapping.

    Represents a type of tradeable instrument with its associated
    Dhan API code.

    Attributes:
        id: Dhan API code for this instrument type.
        name: Human-readable type name (e.g., "EQUITY", "FUTURES").

    Note:
        This is named InstrumentTypeVO to avoid confusion with the
        InstrumentTypeEnum enum.
    """

    id: int
    name: str

    # Predefined types as class attributes
    EQUITY = None  # type: InstrumentTypeVO
    FUTURES = None  # type: InstrumentTypeVO
    OPTIONS = None  # type: InstrumentTypeVO
    CURRENCY = None  # type: InstrumentTypeVO
    COMMODITY = None  # type: InstrumentTypeVO

    @classmethod
    def from_code(cls, code: int) -> Optional["InstrumentTypeVO"]:
        """
        Get instrument type from Dhan code.

        Args:
            code: The Dhan API code for the instrument type.

        Returns:
            The InstrumentTypeVO for the given code, or None if not found.
        """
        types = {
            EQUITY: cls.EQUITY,
            FUTURES: cls.FUTURES,
            OPTIONS: cls.OPTIONS,
            CURRENCY: cls.CURRENCY,
            COMMODITY: cls.COMMODITY,
        }
        return types.get(code)


# Initialize predefined instrument types
InstrumentTypeVO.EQUITY = InstrumentTypeVO(id=EQUITY, name="EQUITY")
InstrumentTypeVO.FUTURES = InstrumentTypeVO(id=FUTURES, name="FUTURES")
InstrumentTypeVO.OPTIONS = InstrumentTypeVO(id=OPTIONS, name="OPTIONS")
InstrumentTypeVO.CURRENCY = InstrumentTypeVO(id=CURRENCY, name="CURRENCY")
InstrumentTypeVO.COMMODITY = InstrumentTypeVO(id=COMMODITY, name="COMMODITY")


@dataclass(frozen=True)
class DepthLevel:
    """
    Single level of market depth.

    Represents a single price level in the order book, containing
    the price, total quantity, and number of orders at that level.

    Attributes:
        price: The price at this depth level.
        quantity: Total quantity available at this price.
        orders: Number of orders at this price level.

    Example:
        >>> level = DepthLevel(price=100.50, quantity=1000, orders=5)
        >>> level.price
        100.5
    """

    price: float
    quantity: int
    orders: int

    @property
    def average_quantity_per_order(self) -> float:
        """Calculate average quantity per order at this level."""
        if self.orders == 0:
            return 0.0
        return self.quantity / self.orders

    @property
    def notional_value(self) -> float:
        """Calculate total notional value at this level."""
        return self.price * self.quantity


@dataclass(frozen=True)
class MarketDepth:
    """
    Market depth with bid and ask levels.

    Represents the order book depth with multiple levels on both
    the bid (buy) and ask (sell) sides.

    Attributes:
        bid_levels: Tuple of bid depth levels (best bid first).
        ask_levels: Tuple of ask depth levels (best ask first).

    Example:
        >>> depth = MarketDepth(
        ...     bid_levels=(
        ...         DepthLevel(price=100.00, quantity=500, orders=3),
        ...         DepthLevel(price=99.50, quantity=1000, orders=5),
        ...     ),
        ...     ask_levels=(
        ...         DepthLevel(price=100.50, quantity=400, orders=2),
        ...         DepthLevel(price=101.00, quantity=800, orders=4),
        ...     )
        ... )
    """

    bid_levels: tuple[DepthLevel, ...]
    ask_levels: tuple[DepthLevel, ...]

    @property
    def best_bid(self) -> Optional[DepthLevel]:
        """Get the best (highest) bid level."""
        return self.bid_levels[0] if self.bid_levels else None

    @property
    def best_ask(self) -> Optional[DepthLevel]:
        """Get the best (lowest) ask level."""
        return self.ask_levels[0] if self.ask_levels else None

    @property
    def spread(self) -> Optional[float]:
        """Calculate the bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    @property
    def mid_price(self) -> Optional[float]:
        """Calculate the mid-point between best bid and ask."""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None

    @property
    def total_bid_quantity(self) -> int:
        """Get total quantity across all bid levels."""
        return sum(level.quantity for level in self.bid_levels)

    @property
    def total_ask_quantity(self) -> int:
        """Get total quantity across all ask levels."""
        return sum(level.quantity for level in self.ask_levels)


@dataclass(frozen=True)
class OHLC:
    """
    OHLC (Open, High, Low, Close) price data.

    Represents the price action for a single period with open,
    high, low, and close prices.

    Attributes:
        open: Opening price for the period.
        high: Highest price during the period.
        low: Lowest price during the period.
        close: Closing price for the period.
    """

    open: float
    high: float
    low: float
    close: float

    @property
    def range(self) -> float:
        """Calculate the price range (high - low)."""
        return self.high - self.low

    @property
    def body_size(self) -> float:
        """Calculate the body size (absolute difference between open and close)."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """Check if the period is bullish (close > open)."""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """Check if the period is bearish (close < open)."""
        return self.close < self.open


@dataclass(frozen=True)
class Greeks:
    """
    Option Greeks.

    Represents the option Greeks which measure sensitivity to
    various factors.

    Attributes:
        iv: Implied Volatility (as decimal, e.g., 0.25 for 25%).
        delta: Rate of change of option price with underlying.
        gamma: Rate of change of delta with underlying.
        theta: Time decay of option price (per day).
        vega: Sensitivity to volatility changes.
    """

    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None

    @property
    def is_complete(self) -> bool:
        """Check if all Greeks are available."""
        return all(
            getattr(self, g) is not None
            for g in ("iv", "delta", "gamma", "theta", "vega")
        )
