"""Parameter objects for AMT analysis.

Reduces method parameter count and groups related parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.gate_pipeline import GateContext
    from app.domain.trading.models.value_objects import AMTResult, OHLC

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.gate_pipeline import GateContext
    from app.domain.trading.models.value_objects import AMTResult, OHLC


@dataclass
class VWAPInput:
    """Input for VWAP calculations."""
    typical_price: float
    volume: float
    time: str


@dataclass
class GatePipelineInput:
    """Input for gate pipeline - reduces 21 parameters to 1 object."""
    
    data: list
    amt_result: "AMTResult"
    tick: "OHLC"
    
    # Market context
    market_state: str = "BALANCED"
    drive_number: int = 0
    drive_entry_valid: bool = False
    aggression_score: float = 0.0
    is_risk_halted: bool = False
    halt_reason: str = ""
    tick_age_seconds: float = 1.1
    symbol: str = ""
    
    # Risk parameters
    max_distance_to_level_ticks: float = 3.0
    probing_aggression_threshold: float = 3.0
    min_aggression_score: float = 2.0
    max_cushion_ticks: float = 10.0
    min_rr_ratio: float = 1.5
    tick_size: float = 0.05
    is_extreme_deviation: bool = False
    
    # NSE-specific filters
    pcr: float = 1.0
    oi_walls: list = field(default_factory=list)
    favor_strategy: str = "NEUTRAL"


@dataclass  
class MarketStateInput:
    """Input for market state detection - reduces 18 parameters."""
    
    price: float
    poc: float
    vah: float
    val: float
    tick_size: float
    
    # State indicators
    has_displacement: bool = False
    has_acceptance: bool = False
    balance_ratio: float = 0.0
    
    # Leg profile
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0
    
    # Session context
    vwap_deviation_sigmas: float | None = None
    ib_break_direction: str = ""
    ib_complete: bool = False
    ib_high: float = 0.0
    ib_low: float = 0.0


@dataclass
class AMTAnalysisInput:
    """Input for AMT analysis - reduces 17 parameters to 1 object."""
    
    # Required data
    data: list = field(default_factory=list)
    
    # Optional profile state
    order_book: "Any" = field(default=None)
    incremental_profile: "Any" = field(default=None)
    
    # MTF context
    daily_data: list = field(default_factory=list)
    hourly_data: list = field(default_factory=list)
    
    # Prior session context
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0
    developing_profile: "Any" = field(default=None)
    
    # Risk context
    cushion_tier: str = "Conservative"
    session_pnl: float = 0.0
    npoc_tracker: "Any" = field(default=None)
    
    # Market context
    underlying: str = "NIFTY"
    option_tick: "Any" = field(default=None)
    cvd_source: str = ""
    symbol: str = ""
    prior_avg_volume: float = 0.0
    displacement_multiplier: float = 1.5


@dataclass
class AMTAnalysisResult:
    """Intermediate result state during AMT analysis pipeline."""
    
    # Profile results
    profile: list = field(default_factory=list)
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    lvns: list = field(default_factory=list)
    hvns: list = field(default_factory=list)
    
    # Market state
    market_state: str = "BALANCED"
    effective_market_state: str = "BALANCED"
    aggression_score: float = 0.0
    profile_shape: str = "D"
    
    # Setup identification
    setup: str = "MEAN_REVERSION"
    
    # Session context
    session_favor_strategy: str = "NEUTRAL"
    pcr: float = 1.0
    squeeze_state = None