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
    profile_shape: str = ""
    cvd_slope: float = 0.0
    cvd_divergence: str = ""  # "BULLISH_DIV", "BEARISH_DIV", or ""
    session_vwap: float = 0.0  # Rolling session VWAP
    vwap_upper_1: float = 0.0  # VWAP + 1σ
    vwap_lower_1: float = 0.0  # VWAP - 1σ
    vwap_upper_2: float = 0.0  # VWAP + 2σ
    vwap_lower_2: float = 0.0  # VWAP - 2σ
    balance_ratio: float = 0.0  # fraction of recent candles inside VA
    # Displacement leg profile
    leg_profile: tuple[VolumeProfileLevel, ...] = ()
    leg_lvns: tuple[float, ...] = ()
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0
    has_displacement: bool = False
    # Market structure classifier output
    market_structure: str = "BALANCE"
    structure_confidence: int = 0
    # Phase 1: Initial Balance + Prior Day Levels
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_complete: bool = False
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0
    gap_type: str = ""       # "SMALL" / "MEDIUM" / "LARGE" / ""
    opening_bias: str = ""   # "LONG_BIAS" / "SHORT_BIAS" / "NEUTRAL" / ""
    # Phase 2: Acceptance vs Rejection
    acceptance_above: bool = False
    acceptance_below: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    price_velocity: float = 0.0
    # Phase 3: Break Detection
    break_direction: str = ""   # "UP" / "DOWN" / ""
    break_type: str = ""        # "INITIATIVE" / "RESPONSIVE" / "ABSORPTION" / ""
    break_level: float = 0.0
    # Phase 4: POC Migration + LVN Play
    poc_signal: str = ""        # "POC_RISING_BULLISH" / "POC_FALLING_BEARISH" / "POC_DIVERGENCE" / ""
    poc_vs_price: str = ""      # "ALIGNED" / "DIVERGENT" / ""
    lvn_play: dict | None = None
    ofi: float = 0.0  # Order Flow Imbalance from order book (-1 to +1)


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
    stacked: bool = False   # Part of stacked imbalance (3+ consecutive)


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


# ---------------------------------------------------------------------------
# AI/ML Prediction Value Objects (shared across domains)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelWeights:
    """Adaptive weights for multi-factor prediction model."""
    trend: float = 0.40
    momentum: float = 0.25
    delta: float = 0.15
    order_book: float = 0.15
    volatility: float = 0.05


@dataclass(frozen=True)
class FactorBreakdown:
    """Individual factor contributions to AI analysis."""
    trend: float = 0.0
    momentum: float = 0.0
    delta: float = 0.0
    order_book: float = 0.0
    volatility: float = 0.0


@dataclass(frozen=True)
class AIAnalysisResult:
    """Result of AI-driven market analysis (prediction engine output)."""
    sentiment: str  # Sentiment enum value
    confidence: float
    long_term_trend: str  # TrendDirection enum value
    volatility_score: float
    quant_score: float
    projected_price: float
    reasoning: tuple[str, ...] = ()
    factor_breakdown: FactorBreakdown = field(default_factory=FactorBreakdown)


# Avoid circular imports — Signal is defined in entities.py
# The forward reference in AMTResult is resolved at runtime.

