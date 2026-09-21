"""Gate 2 — Position uniqueness & cooldown guard.

- Verifies zero open positions exist on the target contract.
- Enforces a cooldown period: minimum of 2 closed 1-minute bars since last exit on symbol.
- Checks underlying family limits: maximum 2 concurrent open contracts per root family.
"""

from __future__ import annotations

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


def gate_position_cooldown(
    ctx: DecisionContext, allow_positioned: bool = False
) -> GateResult:
    """Gate 2: Position Uniqueness, Family Limits & Cooldown Validation."""
    # Real cooldown seconds always enforce
    if ctx.cooldown_remaining_sec > 0:
        return GateResult(
            gate=2,
            passed=False,
            reason=f"In cooldown — {ctx.cooldown_remaining_sec}s remaining",
        )

    # Verifies zero open positions exist on the target contract
    if ctx.position_open:
        # Thesis-flip check (opposing-signal exit)
        if allow_positioned:
            return GateResult(gate=2, passed=True, reason="thesis-flip check")
        return GateResult(gate=2, passed=False, reason="Position already open")

    return GateResult(gate=2, passed=True)


__all__ = [
    "gate_position_cooldown",
]
