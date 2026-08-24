"""Single structural stop. Gate 4, SignalBuilder, and pyramids must share it.

Fabio live placement (spec §11 / Gap #13): 1–2 ticks *inside* the structural
level, toward the market, so the stop fills before the liquidity cascade
through the cluster. ``anchor - 2*tick`` on a long is the *outside* retail
stop — that formula is forbidden here.
"""

from __future__ import annotations

DEFAULT_TICK = 0.05


def _tick(ctx) -> float:
    t = getattr(ctx, "tick_size", 0.0) or 0.0
    return t if t > 0 else DEFAULT_TICK


def structural_anchor(ctx, direction: str) -> float:
    """Same support/resistance the emitted signal will use. Gate 4 must call this."""
    entry = float(ctx.bar.close)
    tick = _tick(ctx)
    val = ctx.val if ctx.val and ctx.val > 0 else None
    vah = ctx.vah if ctx.vah and ctx.vah > 0 else None
    if str(direction).upper() == "LONG":
        if val is not None and vah is not None and val > vah:
            return val
        buy = getattr(ctx, "nearest_buy_print_below", 0.0) or 0.0
        if buy > 0 and entry > buy:
            return buy
        if ctx.leg_lvn and ctx.leg_lvn > 0 and entry > ctx.leg_lvn:
            return ctx.leg_lvn
        if vah is not None and val is not None and entry > vah >= val:
            return vah
        if val is not None and entry > val:
            return val
        if ctx.bar is not None and float(ctx.bar.low) < entry:
            return float(ctx.bar.low)
        return val or ctx.poc or (entry - 5 * tick)
    if val is not None and vah is not None and val > vah:
        return vah
    sell = getattr(ctx, "nearest_sell_print_above", 0.0) or 0.0
    if sell > 0 and entry < sell:
        return sell
    if ctx.leg_lvn and ctx.leg_lvn > 0 and entry < ctx.leg_lvn:
        return ctx.leg_lvn
    if val is not None and vah is not None and entry < val <= vah:
        return val
    if vah is not None and entry < vah:
        return vah
    if ctx.bar is not None and float(ctx.bar.high) > entry:
        return float(ctx.bar.high)
    return vah or ctx.poc or (entry + 5 * tick)


def structural_stop(
    side: str,
    entry: float,
    anchor: float,
    tick: float,
    inside_ticks: int = 2,
) -> float:
    """Return the stop price ``inside_ticks`` inside ``anchor`` toward ``entry``.

    LONG (support below):  sl = anchor + n*tick, still strictly below entry.
    SHORT (resistance above): sl = anchor - n*tick, still strictly above entry.
    """
    step = tick if tick and tick > 0 else DEFAULT_TICK
    offset = inside_ticks * step
    if str(side).upper() == "LONG":
        sl = anchor + offset
        if sl >= entry:
            # ponytail: when anchor is close to entry, place stop 1 tick
            # inside the anchor (toward entry) instead of ignoring it.
            sl = anchor + step if anchor + step < entry else entry - step
        return sl
    sl = anchor - offset
    if sl <= entry:
        sl = anchor - step if anchor - step > entry else entry + step
    return sl
