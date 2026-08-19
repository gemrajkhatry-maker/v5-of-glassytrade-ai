from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


def gate_session_phase(ctx: DecisionContext) -> GateResult:
    if not ctx.session_open:
        return GateResult(gate=1, passed=False, reason="Session closed")
    if not ctx.warmup_complete:
        return GateResult(gate=1, passed=False, reason="Warming up — insufficient bars")
    # Spread & slippage protection: reject if spread is excessively wide (> 3 ticks)
    if ctx.ask > 0 and ctx.bid > 0 and ctx.ask >= ctx.bid:
        spread = ctx.ask - ctx.bid
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        max_spread = max(3.0 * tick, 0.40)
        if spread > max_spread:
            return GateResult(
                gate=1,
                passed=False,
                reason=f"Wide spread ({spread:.2f} > {max_spread:.2f}) — slippage risk",
            )
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
