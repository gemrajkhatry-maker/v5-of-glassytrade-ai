"""GatePipeline — runs gates 1..5 in order and returns every result."""

from quant.decision.context import DecisionContext
from quant.decision.gates_edge import (
    gate_direction_probability,
    gate_triple_a_edge,
)
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
            (3, lambda: gate_direction_probability(ctx)),
            (4, lambda: gate_triple_a_edge(ctx)),
            (5, lambda: gate_risk_reward(ctx)),
        )
        results = []
        for gate_no, run in steps:
            try:
                results.append(run())
            except Exception as exc:
                results.append(GateResult(gate_no, False, f"error: {exc}"))
        return results
