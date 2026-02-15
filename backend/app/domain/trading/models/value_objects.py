"""Domain value objects — immutable data structures with no identity.

These are pure Python dataclasses with *no* framework dependencies (no Pydantic,
no FastAPI).  Serialization to/from JSON is handled by the infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OHLC:
    """Single OHLCV candlestick with order-flow fields."""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    taker_buy_volume: float = 0.0
    delta: float = 0.0


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    quantity: float


@dataclass(frozen=True)
class OrderBook:
    bids: tuple[OrderBookLevel, ...] = ()
    asks: tuple[OrderBookLevel, ...] = ()


# ---------------------------------------------------------------------------
# Volume Profile / AMT
# ---------------------------------------------------------------------------

@dataclass
class VolumeProfileLevel:
    """Mutable during profile construction, frozen after."""
    price: float
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0


@dataclass(frozen=True)
class AggressivePrint:
    price: float
    time: str
    side: str  # "BUY" | "SELL"
    volume: float
    delta: float


@dataclass(frozen=True)
class AMTResult:
    """Output of the Auction Market Theory analysis pipeline."""
    market_state: str  # MarketState enum value
    poc: float
    value_area_high: float
    value_area_low: float
    lvns: tuple[float, ...] = ()
    hvns: tuple[float, ...] = ()
    aggression: float = 0.0
    signal: "Signal | None" = None
    setup: str | None = None
    profile: tuple[VolumeProfileLevel, ...] = ()
    aggressive_prints: tuple[AggressivePrint, ...] = ()


# ---------------------------------------------------------------------------
# Strategy Stats
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyStats:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_profit: float = 0.0
    avg_profit: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0


# ---------------------------------------------------------------------------
# Footprint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FootprintLevel:
    price: float
    bid: float  # Sell volume
    ask: float  # Buy volume
    delta: float
    imbalance: bool = False


@dataclass(frozen=True)
class FootprintCandle:
    time: str
    levels: tuple[FootprintLevel, ...] = ()
    poc_price: float = 0.0
    total_delta: float = 0.0
    step_price: float = 0.0


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AICommandResponse:
    message: str
    config_updates: dict | None = None
    action: str | None = None


# Avoid circular imports — Signal is defined in entities.py
# The forward reference in AMTResult is resolved at runtime.

