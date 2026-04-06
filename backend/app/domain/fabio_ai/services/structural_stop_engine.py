"""Structural Stop Engine — Fabio-compliant stop loss placement.

Fabio Valentini NEVER uses fixed percentage stops. Stops are always placed
at structural invalidation levels:
- AAA/MEAN_REVERSION: SL = one tick beyond the LVN that triggered entry
- MOMENTUM: SL = one tick beyond the IB extreme or prior VAH/VAL that broke
- FAILED_AUCTION: SL = one tick beyond the probe extreme
- Fallback: ATR-based cap to prevent runaway risk

The engine computes the optimal SL based on setup type and market structure,
then applies an ATR multiplier cap: min(structural_sl, atr_2x).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class StopReason(str, Enum):
    """Reason for stop loss placement."""

    LVN = "LVN"  # Beyond LVN that triggered entry
    VA_BOUNDARY = "VA_BOUNDARY"  # Beyond VAH/VAL
    IB_EXTREME = "IB_EXTREME"  # Beyond IB high/low
    PROBE_EXTREME = "PROBE_EXTREME"  # Beyond failed auction probe
    HVN = "HVN"  # Beyond nearest HVN
    ATR_CAP = "ATR_CAP"  # Capped by ATR multiplier
    FALLBACK = "FALLBACK"  # Default fallback


@dataclass(frozen=True)
class StructuralStop:
    """Computed structural stop loss."""

    price: float
    reason: str  # StopReason value
    distance_from_entry: float
    distance_pct: float
    atr_multiple: float  # How many ATR units away
    thesis: str  # Human-readable explanation


def compute_structural_stop(
    entry_price: float,
    direction: str,  # "LONG" or "SHORT"
    setup_type: str = "",  # "AAA", "MOMENTUM", "MEAN_REVERSION", "FAILED_AUCTION"
    lvns: tuple[float, ...] = (),
    hvns: tuple[float, ...] = (),
    vah: float = 0.0,
    val: float = 0.0,
    ib_high: float = 0.0,
    ib_low: float = 0.0,
    atr: float = 0.0,
    tick_size: float = 0.05,
    probe_extreme: float = 0.0,  # For FAILED_AUCTION
) -> StructuralStop:
    """Compute structural stop loss based on setup type and market structure.

    Fabio's rules:
    - AAA/MEAN_REVERSION: SL = one tick beyond LVN that triggered entry
    - MOMENTUM: SL = one tick beyond IB extreme or prior VAH/VAL
    - FAILED_AUCTION: SL = one tick beyond probe extreme
    - All stops capped at 2x ATR to prevent runaway risk

    Args:
        entry_price: Position entry price.
        direction: "LONG" or "SHORT".
        setup_type: Type of setup that triggered entry.
        lvns: Low Volume Node prices.
        hvns: High Volume Node prices.
        vah: Value Area High.
        val: Value Area Low.
        ib_high: Initial Balance high.
        ib_low: Initial Balance low.
        atr: Average True Range (14-period).
        tick_size: Minimum price increment.
        probe_extreme: For FAILED_AUCTION — the extreme of the failed probe.

    Returns:
        StructuralStop with price, reason, and metadata.
    """
    if entry_price <= 0:
        return StructuralStop(
            price=0.0,
            reason=StopReason.FALLBACK.value,
            distance_from_entry=0.0,
            distance_pct=0.0,
            atr_multiple=0.0,
            thesis="Invalid entry price — no stop computed.",
        )

    is_long = direction == "LONG"
    atr_cap = atr * 2.0 if atr > 0 else float("inf")

    # Compute structural SL based on setup type
    if setup_type == "FAILED_AUCTION" and probe_extreme > 0:
        stop = _stop_from_probe_extreme(entry_price, is_long, probe_extreme, tick_size)
    elif setup_type in ("AAA", "MEAN_REVERSION") and lvns:
        stop = _stop_from_lvn(entry_price, is_long, lvns, tick_size)
    elif setup_type == "MOMENTUM":
        stop = _stop_from_ib_or_va(
            entry_price, is_long, ib_high, ib_low, vah, val, tick_size
        )
    else:
        # Fallback: use nearest structural level
        stop = _stop_from_nearest_level(
            entry_price, is_long, lvns, hvns, vah, val, ib_high, ib_low, tick_size
        )

    # Apply ATR cap
    stop_distance = abs(entry_price - stop.price)
    if stop_distance > atr_cap and atr > 0:
        # Cap at 2x ATR
        capped_distance = atr_cap
        if is_long:
            capped_price = entry_price - capped_distance
        else:
            capped_price = entry_price + capped_distance
        stop = StructuralStop(
            price=_round_to_tick(capped_price, tick_size, is_long),
            reason=StopReason.ATR_CAP.value,
            distance_from_entry=capped_distance,
            distance_pct=capped_distance / entry_price,
            atr_multiple=2.0,
            thesis=f"Structural stop ({stop.reason}) capped at 2x ATR ({atr:.2f}). SL={capped_price:.2f}",
        )

    return stop


def _stop_from_probe_extreme(
    entry_price: float,
    is_long: bool,
    probe_extreme: float,
    tick_size: float,
) -> StructuralStop:
    """FAILED_AUCTION: SL one tick beyond probe extreme."""
    if is_long:
        # Probe was below — SL below probe low
        sl = probe_extreme - tick_size
    else:
        # Probe was above — SL above probe high
        sl = probe_extreme + tick_size

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry_price - sl)

    return StructuralStop(
        price=sl,
        reason=StopReason.PROBE_EXTREME.value,
        distance_from_entry=distance,
        distance_pct=distance / entry_price if entry_price > 0 else 0.0,
        atr_multiple=0.0,  # Unknown until ATR passed
        thesis=f"Failed Auction: SL one tick beyond probe extreme ({probe_extreme:.2f}).",
    )


def _stop_from_lvn(
    entry_price: float,
    is_long: bool,
    lvns: tuple[float, ...],
    tick_size: float,
) -> StructuralStop:
    """AAA/MEAN_REVERSION: SL one tick beyond nearest LVN."""
    if is_long:
        # Find nearest LVN below entry
        below_lvns = [lvn for lvn in lvns if lvn < entry_price]
        if below_lvns:
            nearest_lvn = max(below_lvns)  # Closest below
            sl = nearest_lvn - tick_size
        else:
            # No LVN below — use fallback
            return _fallback_stop(entry_price, is_long, tick_size)
    else:
        # Find nearest LVN above entry
        above_lvns = [lvn for lvn in lvns if lvn > entry_price]
        if above_lvns:
            nearest_lvn = min(above_lvns)  # Closest above
            sl = nearest_lvn + tick_size
        else:
            return _fallback_stop(entry_price, is_long, tick_size)

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry_price - sl)

    return StructuralStop(
        price=sl,
        reason=StopReason.LVN.value,
        distance_from_entry=distance,
        distance_pct=distance / entry_price if entry_price > 0 else 0.0,
        atr_multiple=0.0,
        thesis=f"LVN-based stop: nearest LVN at {nearest_lvn:.2f}, SL one tick beyond.",
    )


def _stop_from_ib_or_va(
    entry_price: float,
    is_long: bool,
    ib_high: float,
    ib_low: float,
    vah: float,
    val: float,
    tick_size: float,
) -> StructuralStop:
    """MOMENTUM: SL beyond IB extreme or VA boundary that broke."""
    if is_long:
        # SL below IB low or VAL (whichever is higher/closer)
        levels_below = []
        if ib_low > 0:
            levels_below.append(ib_low)
        if val > 0:
            levels_below.append(val)
        if levels_below:
            nearest = max(levels_below)  # Closest below
            sl = nearest - tick_size
        else:
            return _fallback_stop(entry_price, is_long, tick_size)
    else:
        # SL above IB high or VAH (whichever is lower/closer)
        levels_above = []
        if ib_high > 0:
            levels_above.append(ib_high)
        if vah > 0:
            levels_above.append(vah)
        if levels_above:
            nearest = min(levels_above)  # Closest above
            sl = nearest + tick_size
        else:
            return _fallback_stop(entry_price, is_long, tick_size)

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry_price - sl)
    reason = (
        StopReason.IB_EXTREME.value
        if (is_long and ib_low > 0) or (not is_long and ib_high > 0)
        else StopReason.VA_BOUNDARY.value
    )

    return StructuralStop(
        price=sl,
        reason=reason,
        distance_from_entry=distance,
        distance_pct=distance / entry_price if entry_price > 0 else 0.0,
        atr_multiple=0.0,
        thesis=f"Momentum stop: {reason} at {nearest:.2f}, SL one tick beyond.",
    )


def _stop_from_nearest_level(
    entry_price: float,
    is_long: bool,
    lvns: tuple[float, ...],
    hvns: tuple[float, ...],
    vah: float,
    val: float,
    ib_high: float,
    ib_low: float,
    tick_size: float,
) -> StructuralStop:
    """Fallback: find nearest structural level in stop direction."""
    if is_long:
        # Find nearest level below entry
        levels_below = []
        levels_below.extend(lvn for lvn in lvns if lvn < entry_price)
        levels_below.extend(hvn for hvn in hvns if hvn < entry_price)
        if val > 0 and val < entry_price:
            levels_below.append(val)
        if ib_low > 0 and ib_low < entry_price:
            levels_below.append(ib_low)

        if levels_below:
            nearest = max(levels_below)
            sl = nearest - tick_size
        else:
            return _fallback_stop(entry_price, is_long, tick_size)
    else:
        # Find nearest level above entry
        levels_above = []
        levels_above.extend(lvn for lvn in lvns if lvn > entry_price)
        levels_above.extend(hvn for hvn in hvns if hvn > entry_price)
        if vah > 0 and vah > entry_price:
            levels_above.append(vah)
        if ib_high > 0 and ib_high > entry_price:
            levels_above.append(ib_high)

        if levels_above:
            nearest = min(levels_above)
            sl = nearest + tick_size
        else:
            return _fallback_stop(entry_price, is_long, tick_size)

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry_price - sl)

    return StructuralStop(
        price=sl,
        reason=StopReason.FALLBACK.value,
        distance_from_entry=distance,
        distance_pct=distance / entry_price if entry_price > 0 else 0.0,
        atr_multiple=0.0,
        thesis=f"Fallback stop: nearest structural level at {nearest:.2f}.",
    )


def _fallback_stop(
    entry_price: float, is_long: float, tick_size: float
) -> StructuralStop:
    """Fallback: 1.5% of entry price (last resort)."""
    fallback_pct = 0.015
    distance = entry_price * fallback_pct
    sl = entry_price - distance if is_long else entry_price + distance
    sl = _round_to_tick(sl, tick_size, is_long)

    return StructuralStop(
        price=sl,
        reason=StopReason.FALLBACK.value,
        distance_from_entry=distance,
        distance_pct=fallback_pct,
        atr_multiple=0.0,
        thesis=f"Fallback stop: {fallback_pct:.1%} of entry price (no structural levels found).",
    )


def _round_to_tick(price: float, tick_size: float, is_long: bool) -> float:
    """Round SL to tick boundary — below for LONG, above for SHORT."""
    if tick_size <= 0:
        return price
    if is_long:
        return round(price / tick_size) * tick_size - tick_size  # Round down
    else:
        return round(price / tick_size) * tick_size + tick_size  # Round up
