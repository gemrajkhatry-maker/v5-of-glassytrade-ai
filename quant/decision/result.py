from dataclasses import dataclass


# Fabio AMT playbook pipeline (simplified 2026-08-13): the entry path is
# exactly the documented rules — session filter, one position, the Triple-A
# edge (absorption -> accumulation -> aggression), and R:R >= 1.5. The
# failed-auction-sequence, direction-probability and LLM-consensus gates were
# removed; the LLM stays advisory-only (journal/overseer), never gating.
GATE_NAMES: dict[int, str] = {
    1: "SESSION_PHASE",
    2: "POSITION_COOLDOWN",
    3: "TRIPLE_A_EDGE",
    4: "RISK_REWARD",
}


@dataclass(frozen=True)
class GateResult:
    gate: int            # 1..4
    passed: bool
    reason: str = ""
    extra: str = ""      # e.g. the computed R:R or the failing metric

    @property
    def name(self) -> str:
        return GATE_NAMES.get(self.gate, f"GATE_{self.gate}")
