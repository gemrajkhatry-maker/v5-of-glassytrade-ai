"""AMT domain models split by phase for clean separation."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class VolumeProfileLevel:
    """Single level in volume profile."""
    price: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    
    @property
    def delta(self) -> float:
        """Buy volume minus sell volume."""
        return self.buy_volume - self.sell_volume


@dataclass(frozen=True)
class VolumeProfile:
    """Complete volume profile with POC, VAH, VAL."""
    levels: Tuple[VolumeProfileLevel, ...]
    poc: float  # Point of Control
    vah: float  # Value Area High
    val: float  # Value Area Low
    step: float  # Bucket size


@dataclass(frozen=True)
class Absorption:
    """Detected absorption pattern."""
    bar_index: int
    price: float
    volume: float
    side: str  # "BUY" or "SELL"
    strength: float  # 0.0 to 1.0


@dataclass(frozen=True)
class InitialBalanceResult:
    """Phase 1: Initial Balance + Prior Day Levels"""
    high: float
    low: float
    complete: bool
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0
    gap_type: str = ""  # "SMALL", "MEDIUM", "LARGE"
    opening_bias: str = ""  # "LONG_BIAS", "SHORT_BIAS", "NEUTRAL"


@dataclass(frozen=True)
class AcceptanceResult:
    """Phase 2: Acceptance vs Rejection"""
    accepted_above: bool = False
    accepted_below: bool = False
    rejected_at_high: bool = False
    rejected_at_low: bool = False
    liquidity_sweep: str = ""  # "SWEEP_HIGH", "SWEEP_LOW", or ""


@dataclass(frozen=True)
class BreakResult:
    """Phase 3: Break Detection"""
    direction: str = ""  # "UP" / "DOWN" / ""
    type: str = ""       # "INITIATIVE" / "RESPONSIVE" / "ABSORPTION" / ""
    level: float = 0.0


@dataclass(frozen=True)
class POCMigrationResult:
    """Phase 4: POC Migration + LVN Play"""
    poc_signal: str = ""  # "POC_RISING_BULLISH", "POC_FALLING_BEARISH", etc.
    poc_vs_price: str = ""  # "ALIGNED" / "DIVERGENT" / ""
    lvn_play: Optional[dict] = None


@dataclass(frozen=True)
class TripleAResult:
    """Complete Triple-A analysis result."""
    phase1: InitialBalanceResult
    phase2: AcceptanceResult
    phase3: BreakResult
    phase4: POCMigrationResult
    absorptions: Tuple[Absorption, ...] = ()
    vwap: float = 0.0
    vwap_std: float = 0.0
    
    @property
    def current_phase(self) -> str:
        """Determine current Triple-A phase based on state."""
        if any(abs.price for abs in self.absorptions):
            return "ABSORBING"
        if self.phase2.accepted_above or self.phase2.accepted_below:
            return "ACCUMULATING"
        return "WAITING"


@dataclass(frozen=True)
class Signal:
    """Generated trading signal."""
    type: str  # "LONG", "SHORT", "NO_TRADE"
    entry: float
    sl: float  # Stop loss
    tp: float  # Take profit
    rr: float  # Risk-reward ratio
    confidence: float  # 0.0 to 1.0
    reason: str
    timestamp: float = 0.0


@dataclass(frozen=True)
class CVDPoint:
    """Single CVD data point."""
    bar_index: int
    bid_volume: float
    ask_volume: float
    delta: float  # bid - ask
    cumulative_delta: float
    price: float


@dataclass(frozen=True)
class CVDSnapshot:
    """CVD tracking snapshot."""
    current_delta: float
    cumulative_delta: float
    delta_slope: float  # delta change rate
    divergence: float  # price vs delta divergence
    extremes: Tuple[float, float]  # min/max delta for period


# ---------------------------------------------------------------------------
# Phase 1 Enhancement: CVDState and DivergenceSignal
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CVDState:
    """Complete CVD state snapshot with divergence detection."""
    value: float
    slope: float
    has_divergence: bool
    divergence_type: str  # "BULLISH_DIV" | "BEARISH_DIV" | "NONE"
    z_score: float = 0.0
    timestamps: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DivergenceSignal:
    """Divergence detection result."""
    detected: bool
    type: str
    z_score: float
    price_slope: float
    cvd_slope: float


# ---------------------------------------------------------------------------
# Phase 2 Enhancement: ARState and WickAnalysis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ARState:
    """Acceptance/Rejection engine state."""
    time_above_vah: float
    time_below_val: float
    last_time: str
    price_velocity: float


@dataclass(frozen=True)
class WickAnalysis:
    """Candle wick analysis."""
    upper_wick: float
    lower_wick: float
    body_size: float
    is_upper_wick_dominant: bool
    is_lower_wick_dominant: bool


# ---------------------------------------------------------------------------
# Phase 3 Enhancement: LVNState and HNState
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LVNState:
    """LVN detection state with persistence tracking."""
    price: float
    strength: float
    first_seen_bar: int
    last_seen_bar: int
    confirmation_count: int


@dataclass(frozen=True)
class HVNState:
    """HVN detection state with persistence tracking."""
    price: float
    strength: float
    confirmation_count: int