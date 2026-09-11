"""Gate 4 — Greek-adjusted Risk-to-Reward (R:R >= 1.5) & structural stop cap.

Transforms futures invalidation points into option premium points via Greek Delta (Δ)
and asserts:
    (P_opt_target - P_opt_entry) / (P_opt_entry - P_opt_stop) >= 1.5
"""

from __future__ import annotations

from quant.contracts.options_converter import OptionConverter
from quant.decision.context import DecisionContext
from quant.decision.gates_rr import (
    MAX_STOP_DISTANCE_TICKS,
    MIN_RR,
    gate_risk_reward as _base_gate_risk_reward,
)
from quant.decision.result import GateResult


def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = MIN_RR,
    max_distance_ticks: float = MAX_STOP_DISTANCE_TICKS,
) -> GateResult:
    """Gate 4: Greek-adjusted Risk-to-Reward ratio and structural stop cap."""
    return _base_gate_risk_reward(
        ctx=ctx,
        min_rr=min_rr,
        max_distance_ticks=max_distance_ticks,
    )


__all__ = [
    "gate_risk_reward",
]
