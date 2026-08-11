from dataclasses import dataclass


GATE_NAMES: dict[int, str] = {
    1: "SESSION_PHASE",
    2: "POSITION_COOLDOWN",
    3: "FAILED_AUCTION_SEQUENCE",
    4: "DIRECTION_PROBABILITY",
    5: "TRIPLE_A_EDGE",
    6: "RISK_REWARD",
    7: "LLM_CONSENSUS",
}


@dataclass(frozen=True)
class GateResult:
    gate: int            # 1..7
    passed: bool
    reason: str = ""
    extra: str = ""      # e.g. the computed R:R or the failing metric

    @property
    def name(self) -> str:
        return GATE_NAMES.get(self.gate, f"GATE_{self.gate}")
