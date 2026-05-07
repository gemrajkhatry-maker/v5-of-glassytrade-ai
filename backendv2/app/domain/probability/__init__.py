"""Agent pipeline modules - refactored from god object.

Original agent_pipeline.py was 999 lines. Split into:
- regime_classifier.py (RegimeState, RegimeHysteresis, classify_regime)
- direction_timing.py (DirectionSignal, pick_direction, assess_timing)
- sizing.py (kelly_size, adjust_sl_tp)
- playbook.py (select_playbook, playbook_thresholds, summarize_feature_drivers)
- agent_pipeline.py (AgentDecision, run_agent_pipeline - refactored to use above)
"""

from app.domain.probability.regime_classifier import (
    RegimeState,
    RegimeHysteresis,
    classify_regime,
)
from app.domain.probability.regime_hysteresis_store import RegimeHysteresisStore
from app.domain.probability.direction_timing import (
    DirectionSignal,
    pick_direction,
    assess_timing,
    calculate_timing_probability,
)
from app.domain.probability.sizing import kelly_size, adjust_sl_tp
from app.domain.probability.playbook import (
    select_playbook,
    playbook_thresholds,
    summarize_feature_drivers,
)

__all__ = [
    "RegimeState",
    "RegimeHysteresis",
    "classify_regime",
    "DirectionSignal",
    "pick_direction",
    "assess_timing",
    "calculate_timing_probability",
    "kelly_size",
    "adjust_sl_tp",
    "select_playbook",
    "playbook_thresholds",
    "summarize_feature_drivers",
]

# For backwards compatibility, also expose from fabio_ai services
from app.domain.amt.service.narrative_builder import (
    _build_narrative_session_context,
    _build_narrative_market_state,
    _build_narrative_order_flow,
    _build_core_amt_narrative,
)
from app.domain.fabio_ai.services.response_parser import (
    parse_entry_response,
    parse_overseer_response,
)
from app.domain.fabio_ai.services.prompt_builder import (
    compute_tighten_sl,
)
try:
    from app.domain.probability.features import (
        extract_features,
        extract_features_from_row,
        active_model_features,
        FEATURE_NAMES,
    )
except ImportError:
    extract_features = None
    extract_features_from_row = None
    active_model_features = None
    FEATURE_NAMES = []
from app.domain.probability.agent_pipeline import AgentDecision, run_agent_pipeline

__all__.extend([
    "_build_narrative_session_context",
    "_build_narrative_market_state",
    "_build_narrative_order_flow",
    "_build_core_amt_narrative",
    "parse_entry_response",
    "parse_overseer_response",
    "compute_tighten_sl",
    "extract_features",
    "extract_features_from_row",
    "active_model_features",
    "FEATURE_NAMES",
    "RegimeHysteresisStore",
    "run_agent_pipeline",
    "AgentDecision",
])
