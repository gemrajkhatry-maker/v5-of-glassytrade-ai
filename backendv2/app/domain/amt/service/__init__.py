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
from app.domain.amt.service.footprint_analyzer import FootprintAnalyzer
from app.domain.amt.service.narrative_builder import _build_core_amt_narrative
from app.domain.amt.service.composite_profile import CompositeProfile
from app.domain.amt.service.market_structure_classifier import MarketStructureClassifier
from app.domain.amt.service.npoc_tracker import NPOCTracker
from app.domain.amt.service.order_book_analyzer import OrderBookAnalyzer
from app.domain.amt.service.oi_analyzer import OIAnalyzer
from app.domain.amt.service.opening_type_classifier import classify_opening_type
from app.domain.amt.service.regime_detector import RegimeDetector
from app.domain.amt.service.drive_decay import DriveDecay
from app.domain.amt.service.trade_thesis import TradeThesis, build_trade_thesis, validate_trade_thesis
from app.domain.amt.service.rr_validator import RRValidator
from app.domain.amt.service.order_flow_service import OrderFlowService
from app.domain.amt.service.vwap_service import VWAPConfig, VWAPState, VWAPResult, VWAPService
from app.domain.amt.service.spread_normalizer import SpreadNormalizer, SpreadNormalizationResult
from app.domain.amt.service.prediction_engine import PredictionEngine, PredictionResult
from app.domain.amt.service.lvn_play_engine import LVNPlayEngine, LVNPlay
from app.domain.amt.service.gate_pipeline import (
    GateContext,
    GatePipeline,
    GateResult,
    GateReason,
    GateType,
    run_gate_pipeline,
)
from app.domain.amt.service.entry_gates import calculate_position_size, run_entry_gates
from app.domain.amt.service.orb_breakout import ORBDetector, ORBResult, ORBBreakoutSignal

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
    "FootprintAnalyzer",
    "_build_core_amt_narrative",
    "CompositeProfile",
    "MarketStructureClassifier",
    "NPOCTracker",
    "OrderBookAnalyzer",
    "OIAnalyzer",
    "classify_opening_type",
    "RegimeDetector",
    "DriveDecay",
    "TradeThesis",
    "build_trade_thesis",
    "validate_trade_thesis",
    "RRValidator",
    "OrderFlowService",
    "VWAPConfig",
    "VWAPState",
    "VWAPResult",
    "VWAPService",
    "SpreadNormalizer",
    "SpreadNormalizationResult",
    "PredictionEngine",
    "PredictionResult",
    "LVNPlayEngine",
    "LVNPlay",
    "run_gate_pipeline",
    "GateContext",
    "GatePipeline",
    "GateResult",
    "GateReason",
    "GateType",
    "calculate_position_size",
    "run_entry_gates",
    "ORBDetector",
    "ORBResult",
    "ORBBreakoutSignal",
]
