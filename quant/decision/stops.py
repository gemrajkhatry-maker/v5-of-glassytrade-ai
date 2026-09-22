"""Single structural stop. Gate 4, SignalBuilder, and pyramids must share it.

Fabio playbook §11.1: stop is 1–2 ticks BEHIND the Big Executed Bubble
cluster (outside the cluster, away from the market) — not at arbitrary
candle wicks. The "1–2 ticks inside" convention (§11.2) applies to
take-profit / exit shields only, never to protective stops.
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
    """Structural levels in the trade direction, nearest-first (priority order).

    Absorption bubble cluster is preferred over prints / LVN / VA / bar wick
    (playbook §11.1).
    """
    val = ctx.val if ctx.val and ctx.val > 0 else None
    vah = ctx.vah if ctx.vah and ctx.vah > 0 else None
    if val is not None and vah is not None and val > vah:
        return [val] if side == "LONG" else [vah]

    out: list[float] = []
    if side == "LONG":
        cluster_low = float(getattr(ctx, "absorption_cluster_low", 0.0) or 0.0)
        if cluster_low > 0 and entry > cluster_low:
            out.append(cluster_low)
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
        cluster_high = float(getattr(ctx, "absorption_cluster_high", 0.0) or 0.0)
        if cluster_high > 0 and entry < cluster_high:
            out.append(cluster_high)
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


def structural_anchor(ctx, direction: str) -> float | None:
    """Nearest support/resistance whose stop is not spread-noise.

    Returns None when no structural level clears the min-distance floor —
    callers must reject rather than fabricate a 5-tick synthetic that can
    go ≤0 on cheap premiums.
    """
    entry = float(ctx.bar.close)
    tick = _tick(ctx)
    side = str(direction).upper()
    floor = min_stop_distance(entry, tick)
    for anchor in _anchor_candidates(ctx, side, entry):
        sl = structural_stop(side, entry, anchor, tick)
        if sl <= 0:
            continue
        if abs(entry - sl) >= floor:
            return anchor
    return None


def structural_stop(
    side: str,
    entry: float,
    anchor: float,
    tick: float,
    behind_ticks: int = 2,
) -> float:
    """Return the stop price ``behind_ticks`` BEHIND ``anchor`` (away from entry).

    LONG (support below):  sl = anchor - n*tick, still strictly below entry.
    SHORT (resistance above): sl = anchor + n*tick, still strictly above entry.
    """
    step = tick if tick and tick > 0 else DEFAULT_TICK
    offset = behind_ticks * step
    if str(side).upper() == "LONG":
        sl = anchor - offset
        if sl >= entry:
            sl = entry - step
        return sl
    sl = anchor + offset
    if sl <= entry:
        sl = entry + step
    return sl
