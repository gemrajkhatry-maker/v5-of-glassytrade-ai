"""GatePipeline — Fabio AMT playbook gates (1..4), run in order.

Simplified to the documented Valentini rules (see amt_docs/ and the online
Fabio AMT playbook): trade one session, one position at a time, enter on the
Triple-A edge (absorption -> accumulation -> aggression / VWAP breakout) with
R:R >= 1.5, and stop after the daily-loss limit (SessionRisk at execution).
The LLM advisory never gates an entry — it feeds the journal and overseer.
"""

from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.gates_rr import gate_risk_reward
from quant.decision.gates_session_position import (
    gate_position_cooldown,
    gate_session_phase,
)
from quant.decision.result import GateResult


class GatePipeline:
    def evaluate(self, ctx: DecisionContext) -> list[GateResult]:
        steps = (
            (1, lambda: gate_session_phase(ctx)),
            (2, lambda: gate_position_cooldown(ctx)),
            (3, lambda: gate_triple_a_edge(ctx)),
            (4, lambda: gate_risk_reward(ctx)),
        )
        results = []
        for gate_no, run in steps:
            try:
                results.append(run())
            except Exception as exc:
                results.append(GateResult(gate_no, False, f"error: {exc}"))
        return results
