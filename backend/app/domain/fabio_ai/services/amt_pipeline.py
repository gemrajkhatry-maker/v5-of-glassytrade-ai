"""AMT Analysis Pipeline - Clean architecture with composition over inheritance.

This module provides a cleaner, more modular implementation of AMT analysis
using a pipeline pattern for better testability and maintainability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from app.core.logging import get_logger, log_info, log_error
from app.core.metrics import metrics
from app.core.correlation import get_correlation_id
from app.core.events import publish_event
from app.domain.fabio_ai.strategy.fabio_detectors import (
    compute_value_area_bounds,
    compute_tick_size,
    classify_day_type,
    extract_session_open,
)
from app.domain.services.displacement_detector import detect_displacement_leg, detect_acceptance
from app.domain.fabio_ai.services.amt_parameters import (
    AMTAnalysisInput,
)
from app.domain.services.volume_profile import create_profile
from app.domain.services.lvn_detector import find_lvns, find_hvns
from app.domain.fabio_ai.services.cvd_tracker import CVDTracker
from app.domain.fabio_ai.services.drive_tracker import DriveTracker
from app.domain.fabio_ai.services.profile_classifier import POCMigrationTracker
from app.domain.fabio_ai.services.opening_classifier import OpeningTypeClassifier
from app.domain.fabio_ai.services.mtf_analyzer import MultiTimeframeAMTAnalyzer
from app.domain.fabio_ai.strategy.squeeze_detector import MomentumSqueezeDetector
from app.domain.fabio_ai.services.order_flow_service import OrderFlowService
from app.domain.trading.models.enums import MarketState, SetupType
from app.domain.trading.models.value_objects import AMTResult, OHLC

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline Stage Results (immutable progression through stages)
# ---------------------------------------------------------------------------

@dataclass
class ProfileStageResult:
    """Result from profile building stage."""
    profile: list = field(default_factory=list)
    profile_type: str = "Session"
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    step: float = 0.0
    half_step: float = 0.0


@dataclass  
class MarketStateStageResult:
    """Result from market state detection stage."""
    has_displacement: bool = False
    has_acceptance: bool = False
    balance_ratio: float = 0.0
    state: str = "BALANCED"
    market_state: MarketState = MarketState.BALANCED
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_complete: bool = False
    leg_data: dict = field(default_factory=dict)


@dataclass
class SetupStageResult:
    """Result from setup classification stage."""
    setup: str = "MEAN_REVERSION"
    profile_shape: str = "D"
    extreme_deviation: bool = False


@dataclass
class SessionStageResult:
    """Result from session context stage."""
    session_open: float = 0.0
    day_type: str = "UNKNOWN"
    favor_strategy: str = "NEUTRAL"
    gap_type: str = ""
    opening_bias: str = ""


@dataclass
class MTFStageResult:
    """Result from multi-timeframe alignment stage."""
    alignment: str = ""
    daily_vah: float = 0.0
    daily_val: float = 0.0
    daily_poc: float = 0.0
    hourly_vah: float = 0.0
    hourly_val: float = 0.0
    hourly_poc: float = 0.0


@dataclass
class OrderFlowStageResult:
    """Result from order flow metrics stage."""
    aggression_score: float = 0.0
    has_aggression: bool = False
    ofi: float = 0.0
    cvd_slope: float = 0.0
    cvd_divergence: str = ""
    absorption_detected: bool = False
    absorption_side: str = ""
    big_trade_confirmed: bool = False


# ---------------------------------------------------------------------------
# Pipeline Stages
# ---------------------------------------------------------------------------

def build_profile_stage(input: AMTAnalysisInput) -> ProfileStageResult:
    """Stage 1: Build volume profile and extract POC/VA bounds."""
    result = ProfileStageResult()
    
    # Profile building
    if input.incremental_profile is not None:
        result.profile = input.incremental_profile.get_profile()
        result.profile_type = "Incremental"
    else:
        result.profile = create_profile(input.data)
        result.profile_type = "Session"
    
    # Profile analysis - extract POC, VA using CME two-row pairs method
    if result.profile:
        max_vol = max(p.volume for p in result.profile)
        poc_candidates = [i for i, p in enumerate(result.profile) if p.volume == max_vol]
        
        # Use close price as reference for tie-break
        ref_price = float(input.data[-1].close)
        
        poc_index = min(poc_candidates, key=lambda i: abs(result.profile[i].price - ref_price))
        result.poc, result.vah, result.val, result.step, result.half_step = \
            compute_value_area_bounds(result.profile, poc_index, ref_price)
    
    return result


def compute_market_state_stage(
    input: AMTAnalysisInput, 
    profile: ProfileStageResult,
    tracker: DriveTracker,
    cvd_tracker: CVDTracker,
) -> MarketStateStageResult:
    """Stage 2: Compute market state, displacement, balance ratio."""
    result = MarketStateStageResult()
    
    # Displacement leg detection
    result.leg_data = detect_displacement_leg(
        input.data, 
        getattr(input, 'displacement_multiplier', 1.5)
    )
    result.has_displacement = result.leg_data.get("has_displacement", False)
    
    # Acceptance detection
    result.has_acceptance = detect_acceptance(input.data, profile.vah, profile.val)
    
    # Balance ratio (candles inside VA over last 20)
    balance_window = min(len(input.data), 20)
    if balance_window > 0 and profile.vah > profile.val:
        inside_count = sum(
            1 for d in input.data[-balance_window:] 
            if profile.val <= d.close <= profile.vah
        )
        result.balance_ratio = inside_count / balance_window
    
    # Market state determination (simplified)
    if result.has_displacement and result.balance_ratio < 0.4:
        result.state = "IMBALANCED"
        result.market_state = MarketState.IMBALANCED
    else:
        result.state = "BALANCED"
        result.market_state = MarketState.BALANCED
        
    return result


def classify_setup_stage(
    market_state: MarketStateStageResult,
    profile: ProfileStageResult,
) -> SetupStageResult:
    """Stage 3: Classify setup type based on market state."""
    result = SetupStageResult()
    
    # Setup identification logic
    _setup = SetupType.MEAN_REVERSION
    if market_state.balance_ratio < 0.3 and market_state.has_displacement:
        _setup = SetupType.TREND_MODEL
    elif market_state.has_acceptance:
        _setup = SetupType.TREND_MODEL
    
    result.setup = _setup.value
    result.profile_shape = "D"  # Will be computed properly later
    
    return result


def compute_session_stage(
    input: AMTAnalysisInput,
    market_state: MarketStateStageResult,
) -> SessionStageResult:
    """Stage 4: Compute session context (open, day type, strategy)."""
    result = SessionStageResult()
    
    if input.data:
        result.session_open = extract_session_open(input.data, input.data[-1])
        
        # Detect IB from data (first 12 5-min candles = 60 min)
        ib_complete = len(input.data) >= 12
        ib_high = max(d.high for d in input.data[:12]) if ib_complete else 0.0
        ib_low = min(d.low for d in input.data[:12]) if ib_complete else 0.0
        
        result.day_type = classify_day_type(
            input.data,
            ib_complete,
            ib_high,
            ib_low,
        )
    
    return result


def compute_mtf_stage(
    input: AMTAnalysisInput,
    mtf_analyzer: MultiTimeframeAMTAnalyzer,
) -> MTFStageResult:
    """Stage 5: Compute multi-timeframe alignment."""
    result = MTFStageResult()
    
    if input.daily_data and input.hourly_data and input.data:
        try:
            mtf_result = mtf_analyzer.compute_alignment(
                current_price=float(input.data[-1].close),
                daily_ohlc=input.daily_data,
                hourly_ohlc=input.hourly_data,
            )
            result.alignment = mtf_result.alignment
            result.daily_vah = mtf_result.daily.vah if mtf_result.daily else 0.0
            result.daily_val = mtf_result.daily.val if mtf_result.daily else 0.0
            result.daily_poc = mtf_result.daily.poc if mtf_result.daily else 0.0
            result.hourly_vah = mtf_result.hourly.vah if mtf_result.hourly else 0.0
            result.hourly_val = mtf_result.hourly.val if mtf_result.hourly else 0.0
            result.hourly_poc = mtf_result.hourly.poc if mtf_result.hourly else 0.0
        except Exception:
            pass  # Silently fail on MTF errors
    
    return result


def compute_order_flow_stage(
    input: AMTAnalysisInput,
    profile: ProfileStageResult,
    order_flow_service,
) -> OrderFlowStageResult:
    """Stage 6: Compute order flow metrics (CVD, absorption, OFI, aggression)."""
    result = OrderFlowStageResult()
    
    if order_flow_service:
        try:
            tick_size = compute_tick_size(input.data)
            of_result = order_flow_service.compute_metrics(
                recent_data=input.data,
                order_book=input.order_book,
                current=input.data[-1] if input.data else None,
                lvns=[],  # Will be populated from LVN detection
                vah=profile.vah,
                val=profile.val,
                poc=profile.poc,
                tick_size=tick_size,
            )
            result.aggression_score = of_result.get("aggression_score", 0)
            result.has_aggression = of_result.get("has_aggression", False)
            result.ofi = of_result.get("ofi", 0)
            result.cvd_slope = of_result.get("cvd_state", {}).get("slope", 0) if isinstance(of_result.get("cvd_state"), dict) else 0
            result.absorption_detected = of_result.get("absorption_detected", False)
            result.absorption_side = of_result.get("absorption_side", "")
            result.big_trade_confirmed = of_result.get("big_trade_confirmed", False)
        except Exception:
            pass  # Silently fail on order flow errors
    
    return result


# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------

class AMTPipeline:
    """Clean pipeline implementation of AMT analysis."""
    
    def __init__(self, config=None):
        self.config = config
        self._cvd_tracker = CVDTracker()
        self._drive_tracker = DriveTracker()
        self._poc_tracker = POCMigrationTracker()
        self._opening_classifier = OpeningTypeClassifier()
        self._mtf_analyzer = MultiTimeframeAMTAnalyzer()
        self._squeeze_detector = MomentumSqueezeDetector()
        self._order_flow_service = OrderFlowService()
    
    def analyze(self, data: "AMTAnalysisInput | list[OHLC]", **kwargs) -> AMTResult:
        """Run the AMT analysis pipeline with parallel stages."""
        correlation_id = get_correlation_id()
        symbol = getattr(data, 'symbol', getattr(kwargs, 'symbol', 'UNKNOWN'))
        start_time = time.time()
        
        log_info("amt_pipeline", "Starting AMT analysis", symbol=symbol, correlation_id=correlation_id)
        
        # Handle both AMTAnalysisInput and direct data list
        if isinstance(data, AMTAnalysisInput):
            input = data
        else:
            input = AMTAnalysisInput(data=data, **kwargs)
        
        # Prefetch Stage - validate and prepare input
        try:
            # Prior values remain as provided (default 0.0 if not passed)
            pass
        except Exception as e:
            log_error("amt_pipeline", f"Prefetch stage error: {e}", symbol=symbol)
        
        # Run stages - sequential for now, ready for parallel optimization
        profile_stage = build_profile_stage(input)
        
        # Parallelizable stages (prepare for async execution)
        market_stage = compute_market_state_stage(
            input, profile_stage, self._drive_tracker, self._cvd_tracker
        )
        session_stage = compute_session_stage(input, market_stage)
        
        # These stages can run in parallel
        setup_stage = classify_setup_stage(market_stage, profile_stage)
        mtf_stage = compute_mtf_stage(input, self._mtf_analyzer)
        of_stage = compute_order_flow_stage(input, profile_stage, self._order_flow_service)
        
        # Compute VWAP bands
        vwap_bands = self._compute_vwap_bands(input.data)
        
        # Compute LVNs/HVNs from profile
        lvns = [lvn.price for lvn in find_lvns(profile_stage.profile)]
        hvns = [hvn.price for hvn in find_hvns(profile_stage.profile)]
        
        # Update CVD tracker
        if input.data:
            self._cvd_tracker.update(input.data[-1])
        cvd_state = self._cvd_tracker.state()
        
        duration = time.time() - start_time
        amt_hist = metrics.histogram("amt_pipeline_duration_seconds", "AMT pipeline execution time", {"symbol": symbol})
        amt_hist.observe(duration)
        
        # Publish pipeline completion event
        publish_event(
            "amt_pipeline_completed",
            "amt_pipeline",
            symbol=symbol,
            data={
                "duration_ms": int(duration * 1000),
                "market_state": market_stage.state,
                "setup": setup_stage.setup,
                "profile_type": profile_stage.profile_type,
            }
        )
        
        log_info("amt_pipeline", "AMT analysis completed", 
                 symbol=symbol, duration_ms=int(duration*1000), 
                 correlation_id=correlation_id, stages_completed=4)
        
        # Return result with current state
        
        # Return result with current state
        return AMTResult(
            market_state=market_stage.state,
            poc=profile_stage.poc,
            value_area_high=profile_stage.vah,
            value_area_low=profile_stage.val,
            profile=tuple(profile_stage.profile),
            profile_type=profile_stage.profile_type,
            setup=setup_stage.setup,
            profile_shape=setup_stage.profile_shape,
            session_favor_strategy=session_stage.favor_strategy,
            hourly_vah=mtf_stage.hourly_vah,
            hourly_val=mtf_stage.hourly_val,
            hourly_poc=mtf_stage.hourly_poc,
            daily_vah=mtf_stage.daily_vah,
            daily_val=mtf_stage.daily_val,
            daily_poc=mtf_stage.daily_poc,
            ofi=of_stage.ofi,
            aggression=of_stage.aggression_score,
            session_vwap=vwap_bands["vwap"],
            vwap_upper_1=vwap_bands["upper_1"],
            vwap_lower_1=vwap_bands["lower_1"],
            vwap_upper_2=vwap_bands["upper_2"],
            vwap_lower_2=vwap_bands["lower_2"],
            balance_ratio=market_stage.balance_ratio,
            cvd_slope=cvd_state.slope,
            lvns=tuple(lvns),
            hvns=tuple(hvns),
            day_type=session_stage.day_type,
            prior_poc=input.prior_poc,
            prior_vah=input.prior_vah,
            prior_val=input.prior_val,
        )
    
    def _compute_vwap_bands(self, data: list) -> dict:
        """Compute VWAP and deviation bands."""
        if not data:
            return {"vwap": 0.0, "upper_1": 0.0, "lower_1": 0.0, "upper_2": 0.0, "lower_2": 0.0}
        
        # Compute VWAP
        cum_vol = 0.0
        cum_quote_vol = 0.0
        prices = []
        
        for d in data:
            vol = getattr(d, 'volume', 0) or 0
            high = getattr(d, 'high', 0) or 0
            low = getattr(d, 'low', 0) or 0
            close = getattr(d, 'close', 0) or 0
            typical = (high + low + close) / 3
            cum_vol += vol
            cum_quote_vol += typical * vol
            prices.append(close)
        
        vwap = cum_quote_vol / cum_vol if cum_vol > 0 else 0.0
        
        # Compute std dev of last 20 prices
        recent = prices[-20:] if len(prices) >= 20 else prices
        mean = sum(recent) / len(recent) if recent else 0.0
        variance = sum((p - mean) ** 2 for p in recent) / len(recent) if recent else 0.0
        std = variance ** 0.5 if variance > 0 else 1.0  # Min std of 1.0 for stability
        
        return {
            "vwap": vwap,
            "upper_1": vwap + std * 1.0,
            "lower_1": vwap - std * 1.0,
            "upper_2": vwap + std * 2.0,
            "lower_2": vwap - std * 2.0,
        }