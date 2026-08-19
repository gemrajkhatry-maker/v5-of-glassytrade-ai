"""Gate 4 — risk-reward on the Triple-A edge (Fabio: R:R >= 1.5, trades 2:1)."""

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import TICK_SIZE_NSE_OPTIONS

DEFAULT_TP_MULTIPLIER = 2.0
MIN_RR = 1.5
MAX_STOP_DISTANCE_TICKS = 20.0


def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = MIN_RR,
    max_distance_ticks: float = 999999.0,
) -> GateResult:
    """Gate 4 — risk-reward check (Fabio: R:R >= 1.5)."""
    if ctx is None or ctx.bar is None:
        return GateResult(4, False, "RR fail", "no bar")
    direction = ctx.agent_direction
    if direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "RR fail", "No direction")
    entry = float(ctx.bar.close)
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
    val = ctx.val if ctx.val and ctx.val > 0 else None
    vah = ctx.vah if ctx.vah and ctx.vah > 0 else None
    if direction == "LONG":
        if ctx.leg_lvn and ctx.leg_lvn > 0 and entry > ctx.leg_lvn:
            anchor = ctx.leg_lvn
        elif val is not None and entry > val:
            anchor = val
        else:
            anchor = val or ctx.poc or (entry - 5 * tick)
        sl = anchor - 2 * tick if anchor is not None else (entry - 2 * tick)
        if sl is not None and sl >= entry:
            sl = entry - 2 * tick
        tp = entry + (entry - sl) * DEFAULT_TP_MULTIPLIER if sl is not None else (entry + 4 * tick)
    else:
        if ctx.leg_lvn and ctx.leg_lvn > 0 and entry < ctx.leg_lvn:
            anchor = ctx.leg_lvn
        elif vah is not None and entry < vah:
            anchor = vah
        else:
            anchor = vah or ctx.poc or (entry + 5 * tick)
        sl = anchor + 2 * tick if anchor is not None else (entry + 2 * tick)
        if sl is not None and sl <= entry:
            sl = entry + 2 * tick
        tp = entry - (sl - entry) * DEFAULT_TP_MULTIPLIER if sl is not None else (entry - 4 * tick)
    sl = float(sl)
    tp = float(tp)
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    detail = f"RR={rr:.2f} SL={sl:.2f} TP={tp:.2f}"
    return GateResult(4, rr >= min_rr, "RR pass" if rr >= min_rr else f"RR below {min_rr}", detail)
