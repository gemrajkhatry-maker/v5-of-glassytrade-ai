"""Three-align gate: Market structure + location + confirmation."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Iterable

from app.domain.constants import CVD_SLOPE_EXTREME
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import check_confirmation_bundle

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import AMTResult, OHLC

logger = logging.getLogger(__name__)


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _candle_body(open_price: float, high: float, low: float, close: float) -> float:
    return abs(close - open_price)


def min_candles_gate(data: list, min_candles: int = 6) -> bool:
    return len(data) >= min_candles


def full_body_close_gate(tick: "OHLC", break_level: float, direction: str) -> bool:
    body_size = _candle_body(_to_float(getattr(tick, "open", 0.0), default=0.0), _to_float(getattr(tick, "high", 0.0), default=0.0), _to_float(getattr(tick, "low", 0.0), default=0.0), _to_float(getattr(tick, "close", 0.0), default=0.0))
    rng = _to_float(getattr(tick, "high", 0.0), default=0.0) - _to_float(getattr(tick, "low", 0.0), default=0.0)
    body_pct = body_size / rng if rng > 0 else 0.0
    if body_pct < 0.5:
        return False
    if direction == "LONG":
        return _to_float(getattr(tick, "close", 0.0), default=0.0) > break_level
    if direction == "SHORT":
        return _to_float(getattr(tick, "close", 0.0), default=0.0) < break_level
    return False


def nearest_round_number(price: float) -> float:
    if price < 1000:
        return round(price / 100) * 100
    if price < 10000:
        return round(price / 500) * 500
    return round(price / 1000) * 1000


def cluster_aggressive_prints(prints: Iterable, cluster_pct: float = 0.001) -> list[float]:
    if not prints:
        return []

    normalized = [
        (float(p.price), float(p.volume))
        for p in prints
        if p is not None and float(getattr(p, "volume", 0.0)) > 0 and float(getattr(p, "price", 0.0)) > 0
    ]
    if not normalized:
        return []

    normalized.sort(key=lambda item: item[0])
    clusters: list[tuple[float, float]] = []
    current_cluster = [normalized[0]]

    for price, volume in normalized[1:]:
        ref_price = current_cluster[0][0]
        if abs(price - ref_price) / ref_price <= cluster_pct:
            current_cluster.append((price, volume))
        else:
            total_vol = sum(v for _, v in current_cluster)
            vwap = sum(pr * v for pr, v in current_cluster) / total_vol
            clusters.append((vwap, total_vol))
            current_cluster = [(price, volume)]

    if current_cluster:
        total_vol = sum(v for _, v in current_cluster)
        vwap = sum(pr * v for pr, v in current_cluster) / total_vol
        clusters.append((vwap, total_vol))

    clusters.sort(key=lambda item: item[1], reverse=True)
    return [cluster[0] for cluster in clusters[:5]]


def extract_bubble_levels_from_footprint(fp_domain: dict | None, min_stacked_count: int = 2) -> list[float]:
    if not fp_domain:
        return []

    bubble_levels: list[float] = []
    try:
        values = list(fp_domain.values()) if isinstance(fp_domain, dict) else []
        recent = values[-3:] if len(values) >= 3 else values
        for fp in recent:
            for level in getattr(fp, "levels", ()):
                if not getattr(level, "stacked", False):
                    continue
                if getattr(level, "magnitude", min_stacked_count) >= min_stacked_count:
                    bubble_levels.append(float(getattr(level, "price", 0.0)))
    except TypeError:
        return []
    return [lvl for lvl in bubble_levels if lvl > 0]


def three_align_check(
    data: list["OHLC"],
    amt_result: "AMTResult",
    tick: "OHLC",
    order_book=None,
    ib_high: float = 0.0,
    ib_low: float = 0.0,
    aggressive_levels: list[float] | None = None,
    footprint_domain: dict | None = None,
    return_is_second_drive: bool = False,
    session_info=None,
    tick_size: float = 0.05,
) -> tuple[bool, bool] | tuple[bool, bool, bool]:
    """Return (gate_passed, confirmation_strong[, is_second_drive]).

    Inputs are intentionally tolerant to evolving AMTResult schema.
    """
    del session_info

    poc = _to_float(getattr(amt_result, "poc", 0.0), default=0.0)
    vah = _to_float(getattr(amt_result, "value_area_high", 0.0), default=0.0)
    val = _to_float(getattr(amt_result, "value_area_low", 0.0), default=0.0)
    if not poc or not vah or not val or poc <= 0 or vah <= 0 or val <= 0:
        return (False, False, False) if return_is_second_drive else (False, False)

    if not (math.isfinite(poc) and math.isfinite(vah) and math.isfinite(val)):
        return (False, False, False) if return_is_second_drive else (False, False)

    va_range = vah - val
    if va_range <= poc * 0.001:
        return (False, False, False) if return_is_second_drive else (False, False)

    cvd_slope = _to_float(getattr(amt_result, "cvd_slope", 0.0), default=0.0) or 0.0
    market_state = str(getattr(amt_result, "market_state", "")).upper()
    if not math.isfinite(cvd_slope):
        cvd_slope = 0.0

    if cvd_slope < -CVD_SLOPE_EXTREME and market_state == "BALANCED":
        return (False, False, False) if return_is_second_drive else (False, False)
    if cvd_slope > CVD_SLOPE_EXTREME and market_state == "BALANCED":
        return (False, False, False) if return_is_second_drive else (False, False)

    price_velocity = abs(_to_float(getattr(amt_result, "price_velocity", 0.0), default=0.0) or 0.0)
    if price_velocity > 0.5:
        return (False, False, False) if return_is_second_drive else (False, False)

    if price_velocity > 0.1:
        logger.debug("Three-align passes with elevated velocity: %.3f", price_velocity)

    tick_price = _to_float(getattr(tick, "close", 0.0), default=0.0)
    threshold = max(tick_size * 8, va_range * 0.15) if va_range > 0 else tick_size * 8

    leg_poc = _to_float(getattr(amt_result, "leg_poc", 0.0), default=0.0)
    leg_vah = _to_float(getattr(amt_result, "leg_vah", 0.0), default=0.0)
    leg_val = _to_float(getattr(amt_result, "leg_val", 0.0), default=0.0)
    use_leg = market_state in ("PROBING", "IMBALANCED") and leg_poc is not None and leg_poc > 0

    levels_to_check: list[float] = []
    if use_leg:
        levels_to_check.extend([leg_poc, leg_vah, leg_val, vah, val, poc])
    else:
        levels_to_check.extend([vah, val, poc])

    dev_poc = _to_float(getattr(amt_result, "dev_poc", 0.0), default=0.0)
    dev_vah = _to_float(getattr(amt_result, "dev_vah", 0.0), default=0.0)
    dev_val = _to_float(getattr(amt_result, "dev_val", 0.0), default=0.0)
    if dev_poc and dev_poc > 0:
        levels_to_check.extend([dev_poc, dev_vah, dev_val])
    if not use_leg and leg_poc:
        levels_to_check.extend([leg_poc, leg_vah, leg_val])

    session_vwap = _to_float(getattr(amt_result, "session_vwap", 0.0), default=0.0)
    if session_vwap and session_vwap > 0:
        levels_to_check.append(session_vwap)

    for lv in getattr(amt_result, "lvns", ()) or ():
        if lv > 0:
            levels_to_check.append(float(lv))
    for hv in getattr(amt_result, "hvns", ()) or ():
        if hv > 0:
            levels_to_check.append(float(hv))
    for lv in getattr(amt_result, "leg_lvns", ()) or ():
        if lv > 0:
            levels_to_check.append(float(lv))

    if ib_high and ib_high > 0:
        levels_to_check.append(float(ib_high))
    if ib_low and ib_low > 0:
        levels_to_check.append(float(ib_low))
    if aggressive_levels:
        levels_to_check.extend([float(v) for v in aggressive_levels if float(v) > 0])

    bubble_levels = extract_bubble_levels_from_footprint(footprint_domain)
    levels_to_check.extend(bubble_levels[:3])

    round_level = nearest_round_number(tick_price)
    if round_level > 0:
        levels_to_check.append(round_level)

    near_level = False
    active_level = 0.0
    for level in levels_to_check:
        if level > 0 and abs(tick_price - level) < threshold:
            near_level = True
            active_level = level
            break

    # Legacy second-drive logic (best-effort).
    is_second_drive = False
    if near_level and data and len(data) > 5:
        history = data[:-1] if _to_float(getattr(data[-1], "time", None)) == _to_float(getattr(tick, "time", None), default=None) else data
        recent_touches = 0
        past_touches = 0
        for i, d in enumerate(reversed(list(history[-30:]))):
            d_high = _to_float(getattr(d, "high", None), default=None)
            d_low = _to_float(getattr(d, "low", None), default=None)
            d_close = _to_float(getattr(d, "close", None), default=None)
            if d_high is None or d_low is None or d_close is None:
                continue
            dist = min(abs(d_high - active_level), abs(d_low - active_level), abs(d_close - active_level))
            if i < 3 and dist < threshold:
                recent_touches += 1
            if i >= 3 and dist < threshold:
                past_touches += 1
        is_second_drive = past_touches > 0 and recent_touches == 0

    agg_ok = check_confirmation_bundle(data, tick, order_book)
    divergence_confirmation = bool(getattr(amt_result, "cvd_divergence", None))
    confirmation_strong = agg_ok or divergence_confirmation
    if not confirmation_strong:
        return (False, False, False) if return_is_second_drive else (False, False)

    gate_passed = near_level and confirmation_strong and bool(va_range > 0)
    if not return_is_second_drive:
        return gate_passed, confirmation_strong
    return gate_passed, confirmation_strong, is_second_drive

