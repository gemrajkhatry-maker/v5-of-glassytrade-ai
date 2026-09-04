from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

# Momentum-family setups require the phase table's trend-continuation
# permission; reversion-family setups require the reversion permission.
# Mirrors quant/decision/setup_state.py SetupType taxonomy.
_MOMENTUM_SETUPS = frozenset({"TRIPLE_A", "LVN_SNIPER"})
_REVERSION_SETUPS = frozenset({"VA_FADE", "SECOND_DRIVE"})


def gate_session_phase(ctx: DecisionContext) -> GateResult:
    if not ctx.session_open:
        return GateResult(gate=1, passed=False, reason="Session closed")
    if not ctx.warmup_complete:
        return GateResult(gate=1, passed=False, reason="Warming up — insufficient bars")
    # Session-phase setup permissions (Fabio): midday consolidation blocks
    # trend-continuation plays; phases that forbid reversion block fades.
    evidence = ctx.setup_evidence
    if evidence is not None and evidence.setup_type and evidence.setup_type != "NONE":
        phase_label = ctx.session_phase or "current phase"
        if evidence.setup_type in _MOMENTUM_SETUPS and not ctx.allow_trend:
            return GateResult(
                gate=1,
                passed=False,
                reason=(
                    f"SESSION_PHASE: {evidence.setup_type} blocked — "
                    f"trend continuation not permitted in {phase_label}"
                ),
            )
        if evidence.setup_type in _REVERSION_SETUPS and not ctx.allow_reversion:
            return GateResult(
                gate=1,
                passed=False,
                reason=(
                    f"SESSION_PHASE: {evidence.setup_type} blocked — "
                    f"mean reversion not permitted in {phase_label}"
                ),
            )
    # Spread & slippage protection: reject if spread is excessively wide (> 0.1% of price or 3 ticks)
    if ctx.ask > 0 and ctx.bid > 0 and ctx.ask >= ctx.bid:
        spread = ctx.ask - ctx.bid
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        close_px = float(getattr(ctx.bar, "close", 0) or 0) if ctx.bar is not None else 0.0
        max_spread = max(3.0 * tick, close_px * 0.001, 0.40)
        if spread > max_spread:
            return GateResult(
                gate=1,
                passed=False,
                reason=f"Wide spread ({spread:.2f} > {max_spread:.2f}) — slippage risk",
            )
    return GateResult(gate=1, passed=True)


def gate_position_cooldown(
    ctx: DecisionContext, allow_positioned: bool = False
) -> GateResult:
    # Real cooldown seconds always enforce — allow_positioned bypasses only
    # the open-position blocker below, never a live post-trade cooldown.
    if ctx.cooldown_remaining_sec > 0:
        return GateResult(
            gate=2,
            passed=False,
            reason=f"In cooldown — {ctx.cooldown_remaining_sec}s remaining",
        )
    if ctx.position_open:
        # Thesis-flip check (opposing-signal exit): while evaluating an open
        # position for invalidation the position itself is EXPECTED — pass it
        # through so gates 3-4 still qualify the contrary signal.
        if allow_positioned:
            return GateResult(gate=2, passed=True, reason="thesis-flip check")
        return GateResult(gate=2, passed=False, reason="Position already open")
    return GateResult(gate=2, passed=True)
