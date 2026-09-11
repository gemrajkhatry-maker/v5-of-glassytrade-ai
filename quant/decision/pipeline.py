"""GatePipeline — Fabio AMT playbook gates (1..4), run in order.

Simplified to the documented Valentini rules (see docs/amt/ and the online
Fabio AMT playbook): trade one session, one position at a time, enter on the
Triple-A edge (absorption -> accumulation -> aggression / VWAP breakout) with
R:R >= 1.5, and stop after the daily-loss limit (SessionRisk at execution).
The LLM advisory never gates an entry — it feeds the journal and overseer.
"""

from quant.decision.context import DecisionContext
from quant.decision.gates import (
    gate_position_cooldown,
    gate_risk_reward,
    gate_session_phase,
    gate_triple_a_edge,
)
from quant.decision.result import GateResult


class GatePipeline:
    def evaluate(
        self, ctx: DecisionContext, *, allow_positioned: bool = False
    ) -> list[GateResult]:
        steps = (
            (1, lambda: gate_session_phase(ctx)),
            # allow_positioned=True skips ONLY the open-position blocker
            # (thesis-flip evaluation); real cooldown seconds still enforce.
            (2, lambda: gate_position_cooldown(ctx, allow_positioned)),
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


__all__ = [
    "GatePipeline",
]
