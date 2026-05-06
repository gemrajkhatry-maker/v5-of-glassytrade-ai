"""Fabio AI service layer."""

from app.domain.fabio_ai.services.amt_pipeline import AMTPipeline
from app.domain.fabio_ai.services.alert_manager import AlertManager
from app.domain.fabio_ai.services.absorption_validator import AbsorptionValidator, AbsorptionValidationResult
from app.domain.fabio_ai.services.amt_parameters import AMTAnalysisInput, AMTAnalysisResult
from app.domain.fabio_ai.services.gap_analyzer import GapAnalysis, analyze_gap, classify_gap_enhanced
from app.domain.fabio_ai.services.llm_contract import CANONICAL_RUNTIME_MODEL_FAMILY, ENTRY_CONTRACT_VERSION
from app.domain.fabio_ai.services.llm_rationale_service import LLMRationaleService, RationaleResult
from app.domain.fabio_ai.services.prompt_builder import build_advisory_prompt, build_entry_prompt, build_overseer_prompt
from app.domain.fabio_ai.services.response_parser import OverseerAction, parse_entry_response, parse_overseer_response
from app.domain.fabio_ai.services.profile_factory import IncrementalProfileFactory
from app.domain.fabio_ai.services.profile_selector import ProfileSelector, ProfileType
from app.domain.fabio_ai.services.rule_based_rationale import RationaleContext, RuleBasedRationale
from app.domain.fabio_ai.services.scale_manager import ScaleManager
from app.domain.fabio_ai.services.session_context import SessionInfo, classify_gap, get_session_info, opening_relation
from app.domain.fabio_ai.services.session_context_factory import SessionContextFactory
from app.domain.fabio_ai.services.session_risk_manager import CapitalRiskBand, SessionRiskManager
from app.domain.fabio_ai.services.session_warmup import SessionWarmupFilter
from app.domain.fabio_ai.services.signal_coordinator import EntryEvaluation, SignalCoordinator
from app.domain.fabio_ai.services.underlying_profile_router import UnderlyingProfileRouter
from app.domain.fabio_ai.services.vp_contract_selector import MarketState, VPContractCandidate, VPContractSelector, VPSelectionResult, VolumeProfile
from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard, OptionScannerService, ScanResult

__all__ = [
    "AMTPipeline",
    "AbsorptionValidationResult",
    "AbsorptionValidator",
    "AMTAnalysisInput",
    "AMTAnalysisResult",
    "AlertManager",
    "GapAnalysis",
    "analyze_gap",
    "classify_gap_enhanced",
    "CANONICAL_RUNTIME_MODEL_FAMILY",
    "ENTRY_CONTRACT_VERSION",
    "LLMRationaleService",
    "RationaleResult",
    "build_advisory_prompt",
    "build_entry_prompt",
    "build_overseer_prompt",
    "OverseerAction",
    "parse_entry_response",
    "parse_overseer_response",
    "IncrementalProfileFactory",
    "ProfileSelector",
    "ProfileType",
    "RuleBasedRationale",
    "RationaleContext",
    "ScaleManager",
    "SessionInfo",
    "classify_gap",
    "get_session_info",
    "opening_relation",
    "SessionContextFactory",
    "SessionRiskManager",
    "CapitalRiskBand",
    "SessionWarmupFilter",
    "EntryEvaluation",
    "SignalCoordinator",
    "UnderlyingProfileRouter",
    "ContractSwitchGuard",
    "OptionScannerService",
    "ScanResult",
    "MarketState",
    "VPContractCandidate",
    "VPContractSelector",
    "VPSelectionResult",
    "VolumeProfile",
]

