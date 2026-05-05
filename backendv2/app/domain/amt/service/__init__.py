"""AMT analysis domain services."""

from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.amt.service.volume_profile import build_volume_profile, calculate_vwap
from app.domain.amt.service.lvn_detector import detect_lvn_hvn, detect_lvn_play, LVNLevel, HVNLevel
from app.domain.amt.service.cvd_tracker import CVDTracker, CVDState
from app.domain.amt.service.aggression_scorer import AggressionScorer, AggressionResult, calculate_aggression_score
from app.domain.amt.service.acceptance_rejection import AcceptanceRejectionEngine, ARResult, ARState, WickAnalysis, detect_acceptance_rejection
from app.domain.amt.service.signal_generator import generate_signal, generate_triple_a_signal, Signal
from app.domain.amt.service.break_detector import detect_break, check_ib_break_tick, BreakResult
from app.domain.amt.service.displacement_detector import detect_displacement, Displacement
from app.domain.amt.service.drive_tracker import DriveTracker, DriveState
from app.domain.amt.service.initial_balance_engine import InitialBalanceEngine, calculate_initial_balance, IBResult
from app.domain.amt.service.session_context import SessionContextEngine, SessionContext
from app.domain.amt.service.market_state_engine import detect_market_state, MarketStateResult, MarketState, MarketZone
from app.domain.amt.service.mtf_analyzer import MultiTimeframeAMTAnalyzer, MTFState, MTFAlignment
from app.domain.amt.service.profile_classifier import classify_profile, classify_shape, ProfileClassification, ProfileShape
from app.domain.amt.service.orderflow_detectors import detect_absorptions
from app.domain.amt.service.vwap_service import VWAPConfig, VWAPState, VWAPResult, VWAPService
from app.domain.amt.service.gate_pipeline import (
    GateContext,
    GatePipeline,
    GateResult,
    GateReason,
    GateType,
    run_gate_pipeline,
)
from app.domain.amt.service.entry_gates import calculate_position_size, run_entry_gates

__all__ = [
    "AMTAnalyzer",
    "build_volume_profile",
    "calculate_vwap",
    "detect_lvn_hvn",
    "detect_lvn_play",
    "LVNLevel",
    "HVNLevel",
    "CVDTracker",
    "CVDState",
    "AggressionScorer",
    "AggressionResult",
    "calculate_aggression_score",
    "AcceptanceRejectionEngine",
    "ARResult",
    "ARState",
    "WickAnalysis",
    "detect_acceptance_rejection",
    "generate_signal",
    "generate_triple_a_signal",
    "Signal",
    "detect_break",
    "check_ib_break_tick",
    "BreakResult",
    "detect_displacement",
    "Displacement",
    "DriveTracker",
    "DriveState",
    "InitialBalanceEngine",
    "calculate_initial_balance",
    "IBResult",
    "SessionContextEngine",
    "SessionContext",
    "detect_market_state",
    "MarketStateResult",
    "MarketState",
    "MarketZone",
    "MultiTimeframeAMTAnalyzer",
    "MTFState",
    "MTFAlignment",
    "classify_profile",
    "classify_shape",
    "ProfileClassification",
    "ProfileShape",
    "detect_absorptions",
    "VWAPConfig",
    "VWAPState",
    "VWAPResult",
    "VWAPService",
    "run_gate_pipeline",
    "GateContext",
    "GatePipeline",
    "GateResult",
    "GateReason",
    "GateType",
    "calculate_position_size",
    "run_entry_gates",
]
