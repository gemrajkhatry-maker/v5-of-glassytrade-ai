"""Re-export shim — moved to quant.probability. Delete after importers switch (Phase 3)."""
from quant.probability import (
    RegimeState,
    RegimeHysteresis,
    classify_regime,
    DirectionSignal,
    pick_direction,
    assess_timing,
    calculate_timing_probability,
    kelly_size,
    adjust_sl_tp,
    select_playbook,
    playbook_thresholds,
    summarize_feature_drivers,
)

# For backwards compatibility, also expose from fabio_ai services
from app.domain.fabio_ai.services.prompt_builder import (
    _build_narrative_session_context,
    _build_narrative_market_state,
    _build_narrative_order_flow,
    _build_core_amt_narrative,
)
from app.domain.fabio_ai.services.prompt_builder import (
    parse_entry_response,
    parse_overseer_response,
    compute_tighten_sl,
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
    "_build_narrative_session_context",
    "_build_narrative_market_state",
    "_build_narrative_order_flow",
    "_build_core_amt_narrative",
    "parse_entry_response",
    "parse_overseer_response",
    "compute_tighten_sl",
]
