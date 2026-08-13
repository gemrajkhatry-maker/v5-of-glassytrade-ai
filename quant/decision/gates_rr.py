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
    max_distance_ticks: float = MAX_STOP_DISTANCE_TICKS,
) -> GateResult:
    """Gate 4: the intended direction must offer R:R >= ``min_rr``.

    SL/TP math mirrors SignalBuilder exactly (2 NSE-option ticks INSIDE the
    value-area edge, TP = 2R), so a pass here means the built signal carries
    the same R:R — no gate/builder divergence.
    """
    if ctx is None or ctx.state is None:
        return GateResult(4, False, "no state")
    direction = ctx.agent_direction
    if direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "No direction for R:R")
    state = ctx.state
    entry = float(state.close)
    vp = state.volume_profile
    loc = state.location
    nearest = loc.nearest_level if loc is not None else None
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else TICK_SIZE_NSE_OPTIONS
    if direction == "LONG":
        val = vp.val if vp is not None else None
        anchor = val if val is not None and entry > val else nearest
        sl = anchor - 2 * tick if anchor is not None else None
        tp = entry + (entry - sl) * DEFAULT_TP_MULTIPLIER if sl is not None else None
    else:
        vah = vp.vah if vp is not None else None
        anchor = vah if vah is not None and entry < vah else nearest
        sl = anchor + 2 * tick if anchor is not None else None
        tp = entry - (sl - entry) * DEFAULT_TP_MULTIPLIER if sl is not None else None
    if sl is None or tp is None:
        return GateResult(4, False, "No stop anchor")
    sl = float(sl)
    tp = float(tp)
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    rr_ok = rr >= min_rr
    distance_ok = risk / tick <= max_distance_ticks
    detail = f"RR={rr:.2f} SL={sl:.2f} TP={tp:.2f}"
    if rr_ok and distance_ok:
        return GateResult(4, True, "", detail)
    reason = f"RR {rr:.2f} below {min_rr}" if not rr_ok else \
        f"stop {risk:.2f} exceeds {max_distance_ticks:.0f} ticks"
    return GateResult(4, False, reason, detail)
