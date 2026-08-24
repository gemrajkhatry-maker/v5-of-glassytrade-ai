from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    gate: int            # 1..5
    passed: bool
    reason: str = ""
    extra: str = ""      # e.g. the computed R:R or the failing metric
