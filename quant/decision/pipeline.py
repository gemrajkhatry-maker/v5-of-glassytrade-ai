"""GatePipeline — Fabio AMT playbook gates (1..4), run in order.

Simplified to the documented Valentini rules (see docs/amt/ and the online
Fabio AMT playbook): trade one session, one position at a time, enter on the
Triple-A edge (absorption -> accumulation -> aggression / VWAP breakout) with
R:R >= 1.5, and stop after the daily-loss limit (SessionRisk at execution).
The LLM advisory never gates an entry — it feeds the journal and overseer.
"""

import logging

from quant.decision.context import DecisionContext
from quant.decision.gate_position_cooldown import gate_position_cooldown
from quant.decision.gate_session_phase import gate_session_phase
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.gates_rr import gate_risk_reward
from quant.decision.result import GateResult

logger = logging.getLogger(__name__)


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
                # A raised gate is a crash, not a veto: fail closed but make it
                # observable — distinct reason prefix + ERROR log with traceback.
                logger.error(
                    "GATE_ERROR: gate %d raised: %s", gate_no, exc, exc_info=True
                )
                results.append(
                    GateResult(gate_no, False, f"GATE_ERROR: {exc}")
                )
        return results


__all__ = [
    "GatePipeline",
]
