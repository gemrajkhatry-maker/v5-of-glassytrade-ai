"""Playbook selection for agent pipeline.

Extracted from agent_pipeline.py for separation of concerns.
"""

from __future__ import annotations

from typing import Any

from quant.contracts.value_objects import AMTResult
from quant.probability.regime import RegimeState


def select_playbook(regime: RegimeState, market_state: str) -> str:
    """Select trading playbook based on regime and market state.

    Args:
        regime: Current regime state
        market_state: Current market state string

    Returns:
        Playbook name string
    """
    if regime.regime == "TRENDING":
        return "imbalance_continuation"
    elif regime.regime == "BALANCED":
        return "return_to_value"
    
    return ""


def playbook_thresholds(playbook: str) -> tuple[float, float, float]:
    """Get entry thresholds for playbook.

    Args:
        playbook: Playbook name

    Returns:
        Tuple of (min_confidence, min_probability, min_risk_scale)
    """
    if playbook == "imbalance_continuation":
        return 0.7, 0.6, 0.8
    elif playbook == "return_to_value":
        return 0.6, 0.5, 0.6
    
    return 0.5, 0.5, 0.5


def summarize_feature_drivers(data: dict[str, Any]) -> tuple[str, ...]:
    """Extract top feature drivers from market data.

    Args:
        data: Market data dictionary

    Returns:
        Tuple of feature driver strings
    """
    drivers = []

    # Order flow drivers
    if data.get("delta_imbalance"):
        drivers.append("delta_imbalance")
    if data.get("cvd_slope"):
        drivers.append("cvd_slope")
    
    # Profile drivers
    if data.get("acceptance_above"):
        drivers.append("acceptance_above")
    if data.get("acceptance_below"):
        drivers.append("acceptance_below")
    
    # Volume drivers
    if data.get("above_vah_volume"):
        drivers.append("above_vah_volume")
    if data.get("below_val_volume"):
        drivers.append("below_val_volume")

    return tuple(drivers[:3])  # Top 3