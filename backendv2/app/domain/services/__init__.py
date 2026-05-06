"""Domain services package."""

from .aggressive_prints import (
    AggressivePrintConfig,
    AggressivePrintRegistry,
    compute_aggression_sigma,
    find_aggressive_prints,
)
from .capital_ladder import CapitalLadder, CapitalRung, LadderConfig, RungState
from .candle_metrics import (
    body,
    body_pct,
    body_pct_ohlc,
    body_ohlc,
    candle_range,
    directional_body,
    is_bearish,
    is_bullish,
    lower_wick,
    upper_wick,
    wick_rejection,
)
from .gate_rejection_tracker import GateRejectionTracker
from .market_data_utils import compute_vwap_approx, estimate_tick_delta
from .latency_tracker import LatencySnapshot, LatencyTracker
from .scalp_gate_pipeline import (
    ScalpContext,
    ScalpGate,
    ScalpGateResult,
    evaluate_scalp_gates,
    check_g1_session_timing,
    check_g2_mtf_alignment,
    check_g3_level_proximity,
    check_g4_risk_tier,
    check_g5_portfolio_headroom,
    check_g6_no_double_exposure,
)
from .short_signal_gates import (
    ShortGateResult,
    SHORT_ML_THRESHOLDS,
    check_s1_direction_allowed,
    check_s2_market_state,
    check_s3_ml_probability,
    check_s4_aggression_direction,
    check_s5_contract_type,
    evaluate_short_gates,
)
from .tick_delta import TickDelta, TickDeltaClassifier, candle_delta_proxy
from .vwap_tracker import VWAPResult, VWAPTracker
from .fifteen_sec_trigger import FifteenSecTriggerEngine, TriggerDirection, TriggerResult
from .session_phase_gate import (
    AllowedAction,
    PhaseState,
    SessionPhaseGate,
    TradingPhase,
)
from .state_bus import DataAnomaly, StateBus
from .symbol_registry import SymbolRegistry
from .tick_utils import (
    round_down_to_tick,
    round_to_tick,
    round_up_to_tick,
    tick_decimals,
    ticks_between,
)
from .trade_costs import TradeCosts, compute_trade_costs
from .watchdog import SessionWatchEntry, Watchdog
from .initial_balance_engine import IBLocation, IBState, InitialBalanceEngine
from .ib_breakout_scalp import IBScalpSignal, IBScalpType, IBBreakoutScalpEngine
from .aaa_precondition_engine import AAAPreconditionEngine, Precondition, PreconditionResult
from .option_selection_engine import (
    ContractType,
    Moneyness,
    OptionContract,
    OptionSelectionEngine,
    SelectionResult,
)
from .underlying_futures_provider import (
    DualFeedMapping,
    InstrumentConfig,
    UnderlyingFuturesProvider,
    build_futures_symbol,
    extract_option_date,
)
from .oi_wall_detector import OIWall, OIWallAnalysis, detect_oi_walls, get_key_levels, is_oi_wall_near_price
from .oi_wall_engine import OIWallEngine
from .lvn_play_detector import detect_lvn_play
from .volatility_features import VIXRegime, VolatilityFeatureProvider, VolatilityFeatures
from .one_min_bar_engine import OneMinBarEngine, OneMinBarState
from .mobile_alerts import Alert, AlertLevel, MobileAlertSystem

__all__ = [
    "AggressivePrintConfig",
    "AggressivePrintRegistry",
    "compute_aggression_sigma",
    "find_aggressive_prints",
    "CapitalLadder",
    "CapitalRung",
    "LadderConfig",
    "RungState",
    "GateRejectionTracker",
    "LatencySnapshot",
    "LatencyTracker",
    "AllowedAction",
    "PhaseState",
    "SessionPhaseGate",
    "TradingPhase",
    "DataAnomaly",
    "StateBus",
    "SymbolRegistry",
    "round_down_to_tick",
    "round_to_tick",
    "round_up_to_tick",
    "tick_decimals",
    "ticks_between",
    "body",
    "body_pct",
    "body_pct_ohlc",
    "body_ohlc",
    "candle_range",
    "directional_body",
    "is_bearish",
    "is_bullish",
    "lower_wick",
    "upper_wick",
    "wick_rejection",
    "compute_vwap_approx",
    "estimate_tick_delta",
    "ScalpContext",
    "ScalpGate",
    "ScalpGateResult",
    "evaluate_scalp_gates",
    "check_g1_session_timing",
    "check_g2_mtf_alignment",
    "check_g3_level_proximity",
    "check_g4_risk_tier",
    "check_g5_portfolio_headroom",
    "check_g6_no_double_exposure",
    "ShortGateResult",
    "SHORT_ML_THRESHOLDS",
    "check_s1_direction_allowed",
    "check_s2_market_state",
    "check_s3_ml_probability",
    "check_s4_aggression_direction",
    "check_s5_contract_type",
    "evaluate_short_gates",
    "TickDelta",
    "TickDeltaClassifier",
    "candle_delta_proxy",
    "VWAPResult",
    "VWAPTracker",
    "FifteenSecTriggerEngine",
    "TriggerDirection",
    "TriggerResult",
    "TradeCosts",
    "compute_trade_costs",
    "SessionWatchEntry",
    "Watchdog",
    "IBLocation",
    "IBState",
    "InitialBalanceEngine",
    "IBScalpSignal",
    "IBScalpType",
    "IBBreakoutScalpEngine",
    "Precondition",
    "PreconditionResult",
    "AAAPreconditionEngine",
    "Moneyness",
    "ContractType",
    "OptionContract",
    "SelectionResult",
    "OptionSelectionEngine",
    "InstrumentConfig",
    "DualFeedMapping",
    "build_futures_symbol",
    "extract_option_date",
    "UnderlyingFuturesProvider",
    "OIWall",
    "OIWallAnalysis",
    "detect_oi_walls",
    "get_key_levels",
    "is_oi_wall_near_price",
    "OIWallEngine",
    "detect_lvn_play",
    "VIXRegime",
    "VolatilityFeatureProvider",
    "VolatilityFeatures",
    "OneMinBarEngine",
    "OneMinBarState",
    "Alert",
    "AlertLevel",
    "MobileAlertSystem",
]

