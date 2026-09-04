from __future__ import annotations
from quantv2.types import Context, Signal

MIN_RR = 1.5
MIN_STOP_PCT = 0.001
TP_MULT = 2.0
STOP_CAP_TICKS = 200.0
STOP_CAP_PCT = 0.0075

class StopTooWide(Exception):
    pass

def _anchor(ctx: Context, direction: str) -> float | None:
    e = ctx.bar.close
    if direction == "LONG":
        for lvl in (ctx.val, ctx.bar.low):
            if lvl and lvl > 0 and lvl < e:
                return float(lvl)
        return None
    for lvl in (ctx.vah, ctx.bar.high):
        if lvl and lvl > 0 and lvl > e:
            return float(lvl)
    return None

def build_signal(ctx: Context, direction: str, setup: str) -> Signal | None:
    tick = ctx.tick if ctx.tick and ctx.tick > 0 else 0.05
    e = float(ctx.bar.close)
    a = _anchor(ctx, direction)
    if a is None:
        return None
    sl = a + 2 * tick if direction == "LONG" else a - 2 * tick
    if direction == "LONG" and not (sl < e):
        sl = e - max(2 * tick, e * MIN_STOP_PCT)
    if direction == "SHORT" and not (sl > e):
        sl = e + max(2 * tick, e * MIN_STOP_PCT)
    risk = abs(e - sl)
    if risk < e * MIN_STOP_PCT:
        return None
    cap = max(STOP_CAP_TICKS * tick, e * STOP_CAP_PCT)
    if risk > cap:
        raise StopTooWide(f"risk {risk:.2f} > cap {cap:.2f}")
    tp = e + risk * TP_MULT if direction == "LONG" else e - risk * TP_MULT
    rr = abs(tp - e) / risk
    if rr < MIN_RR:
        return None
    if direction == "LONG" and not (sl < e < tp):
        return None
    if direction == "SHORT" and not (sl > e > tp):
        return None
    return Signal(type=direction, entry=e, sl=sl, tp=tp, rr=rr, setup=setup, symbol=ctx.symbol, timestamp=ctx.bar.time)
