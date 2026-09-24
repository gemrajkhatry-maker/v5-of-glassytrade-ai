"""Gate 4 — structural stop cap on the Triple-A edge (SignalBuilder owns R:R)."""

from quant.contracts.constants import (
    MAX_STOP_DISTANCE_TICKS,
    MIN_RR_RATIO as MIN_RR,
    amt_stop_distance_limit,
)
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import TICK_SIZE_NSE_OPTIONS
from quant.decision.stops import structural_anchor, structural_stop


def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = MIN_RR,
    max_distance_ticks: float = MAX_STOP_DISTANCE_TICKS,
) -> GateResult:
    """Gate 4 — structural stop cap. SignalBuilder is the sole R:R qualifier
    (structural targets >= 1.5 else 2R fallback); this gate reports stop truth."""
    if ctx is None or ctx.bar is None:
        return GateResult(4, False, "RR fail", "no bar")
    direction = ctx.agent_direction
    if direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "RR fail", "No direction")
    entry = float(ctx.bar.close)
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
    anchor = structural_anchor(ctx, direction)
    if anchor is None:
        return GateResult(4, False, "No structural anchor", "stop would be synthetic")
    sl = float(structural_stop(direction, entry, anchor, tick))
    if sl <= 0:
        return GateResult(4, False, "Stop at/below zero", f"SL={sl:.4f} entry={entry:.2f}")
    risk = abs(entry - sl)
    from quant.contracts.instrument_registry import is_option_contract
    scaled_cap_ticks = amt_stop_distance_limit(
        entry,
        tick,
        is_option=is_option_contract(ctx.symbol),
        max_futures_ticks=max_distance_ticks,
    ) / tick
    if risk > scaled_cap_ticks * tick:
        return GateResult(
            4, False,
            f"Stop too wide ({risk / tick:.0f} > {scaled_cap_ticks:.0f} ticks)",
            f"SL={sl:.2f} entry={entry:.2f}",
        )
    # Gate 4 is the stop-width authority only. The synthetic always-2R TP is
    # dropped — it was a fake "RR pass" by construction. SignalBuilder is the
    # sole R:R qualifier (structural targets >= 1.5 else 2R fallback). Report
    # stop truth, not a measured RR we never took.
    detail = (
        f"stop risk={risk / tick:.0f} ticks (cap {scaled_cap_ticks:.0f}) "
        f"| SL={sl:.2f} | RR enforced by SignalBuilder min_rr=1.5"
    )
    return GateResult(4, True, "Stop within cap", detail)
