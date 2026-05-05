"""Structural stop-loss computation for AMT exits."""

from __future__ import annotations

import logging
import math

from app.domain.exit.model.exit_models import StructuralStop, StopReason

logger = logging.getLogger(__name__)


def compute_structural_stop(
    entry_price: float,
    direction: str,
    setup_type: str = "",
    lvns: tuple[float, ...] = (),
    hvns: tuple[float, ...] = (),
    vah: float = 0.0,
    val: float = 0.0,
    ib_high: float = 0.0,
    ib_low: float = 0.0,
    atr: float = 0.0,
    tick_size: float = 0.05,
    probe_extreme: float = 0.0,
) -> StructuralStop:
    if entry_price <= 0:
        return StructuralStop(
            price=0.0,
            reason=StopReason.FALLBACK.value,
            distance_from_entry=0.0,
            distance_pct=0.0,
            atr_multiple=0.0,
            thesis="Invalid entry price — no stop computed.",
        )

    is_long = direction.upper() == "LONG"
    atr_cap = atr * 2.0 if atr > 0 else math.inf

    if setup_type == "FAILED_AUCTION" and probe_extreme > 0:
        stop = _from_probe_extreme(entry_price, is_long, probe_extreme, tick_size)
    elif setup_type in ("AAA", "MEAN_REVERSION") and lvns:
        stop = _from_lvn(entry_price, is_long, lvns, tick_size)
    elif setup_type == "MOMENTUM":
        stop = _from_ib_or_va(entry_price, is_long, ib_high, ib_low, vah, val, tick_size)
    else:
        stop = _from_nearest_level(entry_price, is_long, lvns, hvns, vah, val, ib_high, ib_low, tick_size)

    stop_distance = abs(entry_price - stop.price)
    if stop_distance > atr_cap and atr > 0:
        capped = entry_price - atr_cap if is_long else entry_price + atr_cap
        capped = _round_to_tick(capped, tick_size, is_long)
        stop = StructuralStop(
            price=capped,
            reason=StopReason.ATR_CAP.value,
            distance_from_entry=abs(entry_price - capped),
            distance_pct=abs(entry_price - capped) / entry_price,
            atr_multiple=2.0,
            thesis=f"Structural stop ({stop.reason}) capped at 2x ATR ({atr:.2f}).",
        )

    return stop


def _from_probe_extreme(entry: float, is_long: bool, probe_extreme: float, tick_size: float) -> StructuralStop:
    sl = probe_extreme - tick_size if is_long else probe_extreme + tick_size
    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry - sl)
    return StructuralStop(
        price=sl,
        reason=StopReason.PROBE_EXTREME.value,
        distance_from_entry=distance,
        distance_pct=distance / entry,
        atr_multiple=0.0,
        thesis=f"Failed auction stop one tick beyond probe extreme ({probe_extreme:.2f}).",
    )


def _from_lvn(entry: float, is_long: bool, lvns: tuple[float, ...], tick_size: float) -> StructuralStop:
    if is_long:
        candidates = [lvn for lvn in lvns if lvn < entry]
        if not candidates:
            return _fallback(entry, is_long, tick_size)
        sl = max(candidates) - tick_size
    else:
        candidates = [lvn for lvn in lvns if lvn > entry]
        if not candidates:
            return _fallback(entry, is_long, tick_size)
        sl = min(candidates) + tick_size

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry - sl)
    return StructuralStop(
        price=sl,
        reason=StopReason.LVN.value,
        distance_from_entry=distance,
        distance_pct=distance / entry,
        atr_multiple=0.0,
        thesis=f"LVN stop one tick beyond nearest LVN.",
    )


def _from_ib_or_va(
    entry: float,
    is_long: bool,
    ib_high: float,
    ib_low: float,
    vah: float,
    val: float,
    tick_size: float,
) -> StructuralStop:
    if is_long:
        levels = [lv for lv in (ib_low, val) if lv > 0]
        if not levels:
            return _fallback(entry, is_long, tick_size)
        nearest = max(levels)
        sl = nearest - tick_size
    else:
        levels = [lv for lv in (ib_high, vah) if lv > 0]
        if not levels:
            return _fallback(entry, is_long, tick_size)
        nearest = min(levels)
        sl = nearest + tick_size

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry - sl)
    reason = (
        StopReason.IB_EXTREME.value
        if (is_long and ib_low > 0) or (not is_long and ib_high > 0)
        else StopReason.VA_BOUNDARY.value
    )
    return StructuralStop(
        price=sl,
        reason=reason,
        distance_from_entry=distance,
        distance_pct=distance / entry,
        atr_multiple=0.0,
        thesis=f"Momentum stop from structural boundary at {nearest:.2f}.",
    )


def _from_nearest_level(
    entry: float,
    is_long: bool,
    lvns: tuple[float, ...],
    hvns: tuple[float, ...],
    vah: float,
    val: float,
    ib_high: float,
    ib_low: float,
    tick_size: float,
) -> StructuralStop:
    if is_long:
        levels = [x for x in lvns if x < entry]
        levels.extend(x for x in hvns if x < entry)
        if val > 0 and val < entry:
            levels.append(val)
        if ib_low > 0 and ib_low < entry:
            levels.append(ib_low)
        if not levels:
            return _fallback(entry, is_long, tick_size)
        nearest = max(levels)
        sl = nearest - tick_size
    else:
        levels = [x for x in lvns if x > entry]
        levels.extend(x for x in hvns if x > entry)
        if vah > 0 and vah > entry:
            levels.append(vah)
        if ib_high > 0 and ib_high > entry:
            levels.append(ib_high)
        if not levels:
            return _fallback(entry, is_long, tick_size)
        nearest = min(levels)
        sl = nearest + tick_size

    sl = _round_to_tick(sl, tick_size, is_long)
    distance = abs(entry - sl)
    return StructuralStop(
        price=sl,
        reason=StopReason.FALLBACK.value,
        distance_from_entry=distance,
        distance_pct=distance / entry,
        atr_multiple=0.0,
        thesis=f"Fallback to nearest structural level at {nearest:.2f}.",
    )


def _fallback(entry: float, is_long: bool, tick_size: float) -> StructuralStop:
    distance = entry * 0.015
    sl = entry - distance if is_long else entry + distance
    sl = _round_to_tick(sl, tick_size, is_long)
    return StructuralStop(
        price=sl,
        reason=StopReason.FALLBACK.value,
        distance_from_entry=abs(entry - sl),
        distance_pct=abs(entry - sl) / entry,
        atr_multiple=0.0,
        thesis="Fallback structural stop 1.5% from entry.",
    )


def _round_to_tick(price: float, tick_size: float, is_long: bool) -> float:
    if tick_size <= 0:
        return float(price)
    if is_long:
        return math.floor(price / tick_size) * tick_size
    return math.ceil(price / tick_size) * tick_size
