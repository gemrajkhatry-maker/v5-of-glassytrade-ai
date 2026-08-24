from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


def gate_session_phase(ctx: DecisionContext) -> GateResult:
    if not ctx.session_open:
        return GateResult(gate=1, passed=False, reason="Session closed")
    if not ctx.warmup_complete:
        return GateResult(gate=1, passed=False, reason="Warming up — insufficient bars")
    return GateResult(gate=1, passed=True)


def gate_position_cooldown(ctx: DecisionContext) -> GateResult:
    if ctx.position_open:
        return GateResult(gate=2, passed=False, reason="Position already open")
    if ctx.cooldown_remaining_sec > 0:
        return GateResult(
            gate=2,
            passed=False,
            reason=f"In cooldown — {ctx.cooldown_remaining_sec}s remaining",
        )
    if ctx.risk_halted:
        return GateResult(gate=2, passed=False, reason="Risk halted")
    return GateResult(gate=2, passed=True)
