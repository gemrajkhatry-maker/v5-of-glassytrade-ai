"""Domain value objects — immutable data structures with no identity.

Pure Python dataclasses with no framework dependencies.
Serialization to/from JSON is handled by the infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


def _to_d(v: float | int | str | Decimal) -> Decimal:
    return Decimal(str(v)) if not isinstance(v, Decimal) else v


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OHLC:
    """Single OHLCV candlestick with order-flow fields."""

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
        return cls(
            time=time,
            open=_to_d(open),
            high=_to_d(high),
            low=_to_d(low),
            close=_to_d(close),
            volume=_to_d(volume),
            vwap=_to_d(vwap),
            taker_buy_volume=_to_d(taker_buy_volume),
            delta=_to_d(delta),
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

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume


@dataclass(frozen=True)
class AggressivePrint:
    price: float
    time: str
    side: str  # "BUY" | "SELL"
    volume: float
    delta: float


@dataclass(frozen=True)
class AMTResult:
    """Output of the Auction Market Theory analysis pipeline.

    Stores values directly — no delegation, no field_map.
    This is the post-refactoring simplified version.
    """

    market_state: str = "BALANCED"
    poc: float = 0.0
    value_area_high: float = 0.0
    value_area_low: float = 0.0
    lvns: tuple[float, ...] = ()
    hvns: tuple[float, ...] = ()
    aggression: float = 0.0
    setup: str | None = None
    profile: tuple[VolumeProfileLevel, ...] = ()
    aggressive_prints: tuple[AggressivePrint, ...] = ()
    profile_shape: str = ""
    profile_type: str = "Session"
    cvd_slope: float = 0.0
    cvd_divergence: str = ""
    session_vwap: float = 0.0
    vwap_upper_1: float = 0.0
    vwap_lower_1: float = 0.0
    vwap_upper_2: float = 0.0
    vwap_lower_2: float = 0.0
    vwap_deviation_sigmas: float | None = None
    balance_ratio: float = 0.0
    leg_profile: tuple[VolumeProfileLevel, ...] = ()
    leg_lvns: tuple[float, ...] = ()
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0
    leg_regime: str = ""
    swing_delta: float = 0.0
    has_displacement: bool = False
    market_structure: str = "BALANCE"
    structure_confidence: int = 0
    day_type: str = "UNKNOWN"
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_complete: bool = False
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0
    gap_type: str = ""
    opening_bias: str = ""
    acceptance_above: bool = False
    acceptance_below: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    liquidity_sweep: str = ""
    absorption_side: str = ""
    absorption_range_ratio: float = 0.0
    absorption_vol_ratio: float = 0.0
    price_velocity: float = 0.0
    break_direction: str = ""
    break_type: str = ""
    break_level: float = 0.0
    poc_signal: str = ""
    poc_vs_price: str = ""
    lvn_play: dict | None = None
    ofi: float = 0.0
    dev_poc: float = 0.0
    dev_vah: float = 0.0
    dev_val: float = 0.0
    cushion_tier: str = "Conservative"
    session_pnl: float = 0.0
    npoc_above: float = 0.0
    npoc_below: float = 0.0
    drive_number: int = 0
    drive_entry_valid: bool = False
    mtf_alignment: str = ""
    opening_type: str = ""
    daily_vah: float = 0.0
    daily_val: float = 0.0
    daily_poc: float = 0.0
    hourly_vah: float = 0.0
    hourly_val: float = 0.0
    hourly_poc: float = 0.0
    delta_normalized_option: float = 0.0
    cvd_source: str = ""
    bimodal_active_pole: str = ""
    is_extreme_deviation: bool = False
    underlying_price: float = 0.0
    option_type: str = "UNKNOWN"

    def __replace__(self, **changes) -> "AMTResult":
        """Create a copy with specified fields replaced."""
        field_values = dict(self.__dict__)
        field_values.update(changes)
        return AMTResult(**field_values)


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
class StackedImbalance:
    direction: str
    price_low: float
    price_high: float
    magnitude: int
    candle_time: str


@dataclass(frozen=True)
class FootprintLevel:
    price: float
    bid: float
    ask: float
    delta: float
    imbalance: bool = False
    stacked: bool = False


@dataclass(frozen=True)
class FootprintCandle:
    time: str
    levels: tuple[FootprintLevel, ...] = ()
    poc_price: float = 0.0
    total_delta: float = 0.0
    step_price: float = 0.0


# ---------------------------------------------------------------------------
# AI/ML Value Objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelWeights:
    trend: float = 0.40
    momentum: float = 0.25
    delta: float = 0.15
    order_book: float = 0.15
    volatility: float = 0.05


@dataclass(frozen=True)
class FactorBreakdown:
    trend: float = 0.0
    momentum: float = 0.0
    delta: float = 0.0
    order_book: float = 0.0
    volatility: float = 0.0


@dataclass(frozen=True)
class AIAnalysisResult:
    sentiment: str = "NEUTRAL"
    confidence: float = 0.0
    long_term_trend: str = "SIDEWAYS"
    volatility_score: float = 0.0
    quant_score: float = 0.0
    projected_price: float = 0.0
    reasoning: tuple[str, ...] = ()
    factor_breakdown: FactorBreakdown = field(default_factory=FactorBreakdown)
