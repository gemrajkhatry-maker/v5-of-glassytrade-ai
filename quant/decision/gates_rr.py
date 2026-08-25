"""Gate 4 — risk-reward on the Triple-A edge (Fabio: R:R >= 1.5, trades 2:1)."""

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import TICK_SIZE_NSE_OPTIONS
from quant.decision.stops import structural_anchor, structural_stop

DEFAULT_TP_MULTIPLIER = 2.0
MIN_RR = 1.5
MAX_STOP_DISTANCE_TICKS = 200.0


def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = MIN_RR,
    max_distance_ticks: float = MAX_STOP_DISTANCE_TICKS,
) -> GateResult:
    """Gate 4 — risk-reward check (Fabio: R:R >= 1.5) + structural stop cap."""
    if ctx is None or ctx.bar is None:
        return GateResult(4, False, "RR fail", "no bar")
    direction = ctx.agent_direction
    if direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "RR fail", "No direction")
    entry = float(ctx.bar.close)
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
    anchor = structural_anchor(ctx, direction)
    sl = structural_stop(direction, entry, anchor, tick)
    if direction == "LONG":
        tp = entry + (entry - sl) * DEFAULT_TP_MULTIPLIER
    else:
        tp = entry - (sl - entry) * DEFAULT_TP_MULTIPLIER
    sl = float(sl)
    tp = float(tp)
    risk = abs(entry - sl)
    scaled_cap_ticks = max(max_distance_ticks, (entry * 0.0075) / tick)
    if risk > scaled_cap_ticks * tick:
        return GateResult(
            4, False,
            f"Stop too wide ({risk / tick:.0f} > {scaled_cap_ticks:.0f} ticks)",
            f"SL={sl:.2f} entry={entry:.2f}",
        )
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    detail = f"RR={rr:.2f} SL={sl:.2f} TP={tp:.2f}"
    return GateResult(4, rr >= min_rr, "RR pass" if rr >= min_rr else f"RR below {min_rr}", detail)
