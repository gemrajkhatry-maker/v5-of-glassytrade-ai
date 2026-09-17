"""Single structural stop. Gate 4, SignalBuilder, and pyramids must share it.

Fabio live placement (spec §11 / Gap #13): 1–2 ticks *inside* the structural
level, toward the market, so the stop fills before the liquidity cascade
through the cluster. ``anchor - 2*tick`` on a long is the *outside* retail
stop — that formula is forbidden here.
"""

from __future__ import annotations

DEFAULT_TICK = 0.05
# Fabio: a stop closer than 0.1% of price is spread noise, not structure.
MIN_STOP_DISTANCE_PCT = 0.1


def _tick(ctx) -> float:
    t = getattr(ctx, "tick_size", 0.0) or 0.0
    return t if t > 0 else DEFAULT_TICK


def min_stop_distance(entry: float, tick: float, pct: float = MIN_STOP_DISTANCE_PCT) -> float:
    """Smallest tradeable stop distance: at least 2 ticks and at least ``pct``% of entry."""
    step = tick if tick and tick > 0 else DEFAULT_TICK
    return max(2.0 * step, abs(entry) * (pct / 100.0))


def _anchor_candidates(ctx, side: str, entry: float) -> list[float]:
    """Structural levels in the trade direction, nearest-first (priority order)."""
    val = ctx.val if ctx.val and ctx.val > 0 else None
    vah = ctx.vah if ctx.vah and ctx.vah > 0 else None
    if val is not None and vah is not None and val > vah:
        # malformed VA — the nearer edge is the only sane level
        return [val] if side == "LONG" else [vah]

    out: list[float] = []
    if side == "LONG":
        buy = getattr(ctx, "nearest_buy_print_below", 0.0) or 0.0
        if buy > 0 and entry > buy:
            out.append(float(buy))
        if ctx.leg_lvn and ctx.leg_lvn > 0 and entry > ctx.leg_lvn:
            out.append(float(ctx.leg_lvn))
        if vah is not None and val is not None and entry > vah >= val:
            out.append(float(vah))
        if val is not None and entry > val:
            out.append(float(val))
        if ctx.bar is not None and float(ctx.bar.low) < entry:
            out.append(float(ctx.bar.low))
    else:
        sell = getattr(ctx, "nearest_sell_print_above", 0.0) or 0.0
        if sell > 0 and entry < sell:
            out.append(float(sell))
        if ctx.leg_lvn and ctx.leg_lvn > 0 and entry < ctx.leg_lvn:
            out.append(float(ctx.leg_lvn))
        if val is not None and vah is not None and entry < val <= vah:
            out.append(float(val))
        if vah is not None and entry < vah:
            out.append(float(vah))
        if ctx.bar is not None and float(ctx.bar.high) > entry:
            out.append(float(ctx.bar.high))
    return out


def structural_anchor(ctx, direction: str) -> float:
    """Nearest support/resistance whose stop is not spread-noise. Gate 4 must call this.

    Walks the structural levels nearest-first and returns the first one that
    produces a stop at least ``min_stop_distance`` from entry. When every
    structural level sits inside the noise band, the stop is placed at the
    minimum distance from entry. This keeps Gate 4's computed R:R identical to
    the stop SignalBuilder will actually emit — a thin anchor used to make Gate 4
    approve on a stop the builder then dropped as "thin stop".
    """
    entry = float(ctx.bar.close)
    tick = _tick(ctx)
    side = str(direction).upper()
    floor = min_stop_distance(entry, tick)
    for anchor in _anchor_candidates(ctx, side, entry):
        sl = structural_stop(side, entry, anchor, tick)
        if abs(entry - sl) >= floor:
            return anchor
    return entry - 5.0 * tick if side == "LONG" else entry + 5.0 * tick


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
