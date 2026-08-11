from dataclasses import dataclass


GATE_NAMES: dict[int, str] = {
    1: "SESSION_PHASE",
    2: "POSITION_COOLDOWN",
    3: "DIRECTION_PROBABILITY",
    4: "TRIPLE_A_EDGE",
    5: "RISK_REWARD",
    6: "LLM_CONSENSUS",
}


@dataclass(frozen=True)
class GateResult:
    gate: int            # 1..6
    passed: bool
    reason: str = ""
    extra: str = ""      # e.g. the computed R:R or the failing metric

    @property
    def name(self) -> str:
        return GATE_NAMES.get(self.gate, f"GATE_{self.gate}")
