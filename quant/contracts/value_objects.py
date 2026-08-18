"""Domain value objects — immutable data structures with no identity.

These are pure Python dataclasses with *no* framework dependencies (no Pydantic,
no FastAPI).  Serialization to/from JSON is handled by the infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OHLC:
    """Single OHLCV candlestick with order-flow fields.

    All monetary values use Decimal for precision in financial calculations.
    Use OHLC.create() factory for convenient float-to-Decimal conversion.
    """

    time: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    vwap: Decimal = field(default_factory=lambda: Decimal("0"))
    taker_buy_volume: Decimal = field(default_factory=lambda: Decimal("0"))
    delta: Decimal = field(default_factory=lambda: Decimal("0"))

    @classmethod
    def create(
        cls,
        time: str,
        open: float | Decimal,
        high: float | Decimal,
        low: float | Decimal,
        close: float | Decimal,
        volume: float | Decimal,
        vwap: float | Decimal = 0,
        taker_buy_volume: float | Decimal = 0,
        delta: float | Decimal = 0,
    ) -> "OHLC":
        """Factory method that accepts float or Decimal for all numeric fields."""

        def to_d(v: float | int | str | Decimal) -> Decimal:
            return Decimal(str(v)) if not isinstance(v, Decimal) else v

        return cls(
            time=time,
            open=to_d(open),
            high=to_d(high),
            low=to_d(low),
            close=to_d(close),
            volume=to_d(volume),
            vwap=to_d(vwap),
            taker_buy_volume=to_d(taker_buy_volume),
            delta=to_d(delta),
        )

    def to_float(self) -> "FloatOHLC":
        """Convert Decimal OHLC to FloatOHLC for float-based analysis kernels."""
        return FloatOHLC(
            time=self.time,
            open=float(self.open),
            high=float(self.high),
            low=float(self.low),
            close=float(self.close),
            volume=float(self.volume),
            vwap=float(self.vwap),
            taker_buy_volume=float(self.taker_buy_volume),
            delta=float(self.delta),
        )


@dataclass(frozen=True)
class FloatOHLC:
    """Float-based candlestick for fast numeric calculations and analysis kernels."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    taker_buy_volume: float = 0.0
    delta: float = 0.0

    def to_decimal(self) -> OHLC:
        """Convert FloatOHLC to Decimal OHLC."""
        return OHLC.create(
            time=self.time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            vwap=self.vwap,
            taker_buy_volume=self.taker_buy_volume,
            delta=self.delta,
        )

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
class ValueMigration:
    """Session VA development between successive 15-minute windows.

    Samples (POC, VAH, VAL) once per 15-minute window of the session clock and
    reports the drift of the latest completed window vs the previous one — so
    the ongoing development of the session value area is explicit (Fabio: value
    migrates as the auction progresses; freezing it breaks LOCATION reads).
    """

    direction: str = "INSUFFICIENT"  # MIGRATING_UP / MIGRATING_DOWN / EXPANDING / CONTRACTING / FLAT
    poc_drift: float = 0.0  # POC change vs previous window
    vah_drift: float = 0.0  # VAH change vs previous window
    val_drift: float = 0.0  # VAL change vs previous window
    window_label: str = ""  # e.g. "09:15→09:30"
    has_migration: bool = False  # False until two windows have closed


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
    # DEPRECATED: signals now generated exclusively by SignalPipeline.
    # This field is kept for backward compatibility but will always be None.
    # Signal creation goes through app.domain.fabio_ai.services.entry_gates.signal_builder.
    signal: "Signal | None" = None
    setup: str | None = None
    profile: tuple[VolumeProfileLevel, ...] = ()
    aggressive_prints: tuple[AggressivePrint, ...] = ()
    profile_shape: str = ""
    profile_type: str = "Session"  # "Session", "Combined", or "Leg"
    cvd_slope: float = 0.0
    cvd_divergence: str = ""  # "BULLISH_DIV", "BEARISH_DIV", or ""
    session_vwap: float = 0.0  # Rolling session VWAP
    vwap_upper_1: float = 0.0  # VWAP + 1σ
    vwap_lower_1: float = 0.0  # VWAP - 1σ
    vwap_upper_2: float = 0.0  # VWAP + 2σ
    vwap_lower_2: float = 0.0  # VWAP - 2σ
    vwap_deviation_sigmas: float | None = None  # None when vwap_std=0 (insufficient data); frontend shows "N/A"
    balance_ratio: float = 0.0  # fraction of recent candles inside VA
    # Displacement leg profile
    leg_profile: tuple[VolumeProfileLevel, ...] = ()
    leg_lvns: tuple[float, ...] = ()
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0
    leg_regime: str = ""  # Regime of the displacement leg (BALANCED/TRENDING/NO_TRADE)
    swing_delta: float = 0.0
    has_displacement: bool = False
    # Market structure classifier output
    market_structure: str = "BALANCE"
    structure_confidence: int = 0
    day_type: str = "UNKNOWN"
    # Phase 1: Initial Balance + Prior Day Levels
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_complete: bool = False
    ib_poc: float = 0.0
    ib_vah: float = 0.0
    ib_val: float = 0.0
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0
    gap_type: str = ""  # "SMALL" / "MEDIUM" / "LARGE" / ""
    opening_bias: str = ""  # "LONG_BIAS" / "SHORT_BIAS" / "NEUTRAL" / ""
    # Phase 2: Acceptance vs Rejection
    acceptance_above: bool = False
    acceptance_below: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    liquidity_sweep: str = ""
    # #22: Absorption context (primary AAA/Failed Auction trigger)
    absorption_side: str = (
        ""  # "SELL_ABSORBED" (bullish) | "BUY_ABSORBED" (bearish) | ""
    )
    absorption_range_ratio: float = 0.0
    absorption_vol_ratio: float = 0.0  # "SWEEP_HIGH" / "SWEEP_LOW" / ""
    price_velocity: float = 0.0
    # Phase 3: Break Detection
    break_direction: str = ""  # "UP" / "DOWN" / ""
    break_type: str = ""  # "INITIATIVE" / "RESPONSIVE" / "ABSORPTION" / ""
    break_level: float = 0.0
    # Phase 4: POC Migration + LVN Play
    poc_signal: str = (
        ""  # "POC_RISING_BULLISH" / "POC_FALLING_BEARISH" / "POC_DIVERGENCE" / ""
    )
    poc_vs_price: str = ""  # "ALIGNED" / "DIVERGENT" / ""
    lvn_play: dict | None = None
    ofi: float = 0.0  # Order Flow Imbalance from order book (-1 to +1)
    # Depth-derived order book imbalance ([-1, 1], +1 = bid-heavy) from the
    # live 5-level depth snapshot — gate 3's order-flow aggression (A3) input.
    obi: float = 0.0
    # Developing Value Area (short lookback — adapts fast to large moves)
    dev_poc: float = 0.0
    dev_vah: float = 0.0
    dev_val: float = 0.0
    # Cushion System State
    cushion_tier: str = "Conservative"
    session_pnl: float = 0.0
    bubble_retests: list[AggressivePrint] = field(default_factory=list)
    # NPOC (Naked POC) — secondary targets for P3 trailing
    npoc_above: float = 0.0  # Nearest unfilled NPOC above current price
    npoc_below: float = 0.0  # Nearest unfilled NPOC below current price
    # Drive state (FR-05) — populated by DriveTracker in AMTAnalyzer
    drive_number: int = 0          # 0 = no level tested yet, 1 = D1, 2 = D2, 3+ = exhausted
    drive_entry_valid: bool = False  # True only for D2 with D1 rejected
    # Phase 5: Multi-Timeframe (MTF) Alignment
    mtf_alignment: str = ""  # "ALIGNED_BULLISH" / "ALIGNED_BEARISH" / "DIVERGENT" / ""
    opening_type: str = ""   # "OPEN_DRIVE" / "OPEN_TEST_REJECTION" / "OPEN_REJECTION_REVERSE" / "OPEN_AUCTION"
    # Higher Timeframe Levels
    daily_vah: float = 0.0
    daily_val: float = 0.0
    daily_poc: float = 0.0
    hourly_vah: float = 0.0
    hourly_val: float = 0.0
    hourly_poc: float = 0.0
    # Per-symbol delta (from option tick, not underlying) — ensures isolation across symbols
    delta_normalized_option: float = 0.0  # Normalized delta from option tick (per-symbol isolation)
    # CVD data source indicator — "underlying" when computed from futures, "option" when from option premium
    cvd_source: str = ""
    # Bimodal active pole — "UPPER" or "LOWER" when profile shape is B-bimodal
    bimodal_active_pole: str = ""
    # New: Extreme deviation escalation (> 3.0 sigma)
    is_extreme_deviation: bool = False
    underlying_price: float = 0.0
    # Fix 1: Option type for direction labeling (CALL/PUT/UNKNOWN)
    option_type: str = "UNKNOWN"
    # Session VA development over successive 15-min windows (ValueMigration)
    value_migration: ValueMigration = ValueMigration()


# ---------------------------------------------------------------------------
# Strategy Stats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyStats:
    """Strategy performance statistics.

    Note: stored as float for JSON serialization compatibility.
    Internal calculations use Decimal for precision.
    """

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
class StackedImbalance:
    """Consecutive footprint imbalance levels in one direction (volume bubble)."""

    direction: str  # "BUY" or "SELL"
    price_low: float
    price_high: float
    magnitude: int  # number of consecutive imbalance levels
    candle_time: str


@dataclass(frozen=True)
class FootprintLevel:
    price: float
    bid: float  # Sell volume
    ask: float  # Buy volume
    delta: float
    imbalance: bool = False
    stacked: bool = False  # Part of stacked imbalance (3+ consecutive)


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
