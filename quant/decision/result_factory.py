"""Factory for decision result dicts — eliminates ~150 lines of copy-paste.

The same ~20-key dict structure was duplicated across 7+ sites in
timesfm_agents.py and timesfm_engine.py. This factory centralizes the
construction so schema changes happen in one place.
"""
from __future__ import annotations

from typing import Any


def _resolve_regime(market_state: Any) -> str:
    """Extract regime string from MarketState enum or string."""
    if hasattr(market_state, "value"):
        return str(market_state.value)
    return str(market_state or "BALANCED")


def _resolve_timing(session_phase: Any) -> str:
    """Extract timing string from session phase."""
    return str(session_phase or "REGULAR")


def build_decision_result(
    *,
    role: str,
    action: str,
    direction: str,
    setup: str,
    reason: str,
    confidence: str,
    confidence_score: float,
    rationale: str,
    forecast: Any,
    gate_results: list[dict],
    active_position: dict | None,
    symbol: str,
    entry_price: float,
    market_state: Any,
    session_phase: Any,
    # Optional overrides:
    dynamic_trail_stop: float | None = None,
    model_label: str | None = None,
    size_fraction: float = 0.0,
    timing_override: str | None = None,
) -> dict:
    """Build a complete decision result dict.

    All repeated expressions (regime, timing, modelVersions) are
    computed once here instead of duplicated at every call site.
    """
    forecast_steps = list(forecast.forecast_steps) if forecast else []
    q_spread = round(float(forecast.q_spread), 4) if forecast else 0.0
    mean_forecast = round(float(forecast.mean_forecast), 2) if forecast else 0.0
    lat_ms = round(forecast.lat_ms, 1) if forecast else 0.0

    return {
        "role": role,
        "action": action,
        "direction": direction,
        "setup": setup,
        "reason": reason,
        "confidence": confidence,
        "confidenceScore": round(confidence_score, 3),
        "rationale": rationale,
        "forecastSteps": forecast_steps,
        "quantileSpread": q_spread,
        "meanForecast": mean_forecast,
        "gateResults": gate_results,
        "activePosition": active_position,
        "dynamicTrailStop": round(dynamic_trail_stop, 2) if dynamic_trail_stop is not None else None,
        "source": "TIMESFM_3.0_NATIVE",
        "latencyMs": lat_ms,
        "modelLabel": model_label or f"TimesFM-{role}-{action}",
        "modelVersions": {"timesfm": "3.0", "engine": "native_direct"},
        "regime": _resolve_regime(market_state),
        "timing": timing_override or _resolve_timing(session_phase),
        "sizeFraction": size_fraction,
        "latencyUs": int(lat_ms * 1000),
    }


def build_gate_results(
    g1_passed: bool, g1_msg: str,
    g2_passed: bool, g2_msg: str,
    g3_passed: bool, g3_msg: str,
    g4_passed: bool, g4_msg: str,
) -> list[dict]:
    """Build the standard 4-gate result list.

    Eliminates ~60 lines of copy-paste across timesfm_agents.py and
    timesfm_engine.py where the same [gate1, gate2, gate3, gate4] list
    structure was constructed from scratch at every site.
    """
    return [
        {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": g1_passed, "message": g1_msg},
        {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": g2_passed, "message": g2_msg},
        {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": g3_passed, "message": g3_msg},
        {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": g4_passed, "message": g4_msg},
    ]
