"""Gate 6 — risk-reward check on the Triple-A edge."""

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

DEFAULT_TP_MULTIPLIER = 2.0
DEFAULT_TICK_SIZE = 0.05


def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = 1.5,
    max_distance_ticks: float = 20.0,
) -> GateResult:
    if ctx is None or ctx.state is None:
        return GateResult(6, False, "no state")
    state = ctx.state
    signal = state.triple_a_signal
    if signal not in ("LONG", "SHORT"):
        return GateResult(6, False, "No Triple-A signal for R:R")
    entry = float(state.close)
    vp = state.volume_profile
    loc = state.location
    nearest = loc.nearest_level if loc is not None else None
    step = float(vp.step) if vp is not None else 0.0
    if signal == "LONG":
        val = vp.val if vp is not None else None
        anchor = val if val is not None and entry > val else nearest
        sl = anchor - step if step > 0 else anchor
        tp = entry + (entry - sl) * DEFAULT_TP_MULTIPLIER
    else:
        vah = vp.vah if vp is not None else None
        anchor = vah if vah is not None and entry < vah else nearest
        sl = anchor + step if step > 0 else anchor
        tp = entry - (sl - entry) * DEFAULT_TP_MULTIPLIER
    if sl is None:
        return GateResult(6, False, "No stop anchor")
    sl = float(sl)
    tp = float(tp)
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else DEFAULT_TICK_SIZE
    rr_ok = rr >= min_rr
    distance_ok = risk / tick <= max_distance_ticks
    detail = f"RR={rr:.2f} SL={sl:.2f} TP={tp:.2f}"
    if rr_ok and distance_ok:
        return GateResult(6, True, "", detail)
    reason = f"RR {rr:.2f} below {min_rr}" if not rr_ok else \
        f"stop {risk:.2f} exceeds {max_distance_ticks:.0f} ticks"
    return GateResult(6, False, reason, detail)
