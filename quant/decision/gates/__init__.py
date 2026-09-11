"""Deterministic 4-Gate Pipeline Gates."""

from __future__ import annotations

from quant.decision.gates.gate_edge import gate_triple_a_edge
from quant.decision.gates.gate_position_cooldown import gate_position_cooldown
from quant.decision.gates.gate_risk_reward import gate_risk_reward
from quant.decision.gates.gate_session_phase import gate_session_phase

__all__ = [
    "gate_position_cooldown",
    "gate_risk_reward",
    "gate_session_phase",
    "gate_triple_a_edge",
]
