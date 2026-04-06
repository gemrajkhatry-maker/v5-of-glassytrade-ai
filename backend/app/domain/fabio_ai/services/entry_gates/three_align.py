"""Three-Align Gate — Market State + Location + Confirmation.

FABIO'S RULE: ALL THREE MUST ALIGN.
1. Market State (BALANCED or IMBALANCED)
2. Location (price near structural level)
3. Aggression/Confirmation (volume impulse + delta + spread)

Pure, stateless quant functions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


def min_candles_gate(data: list, min_candles: int = 6) -> bool:
    """Block entry if insufficient candles have formed since session start.

    Fabio rule: Don't trade first 15-30 minutes.
    """
    return len(data) >= min_candles


def full_body_close_gate(tick: OHLC, break_level: float, direction: str) -> bool:
    """Fabio rule: Require full body candle close above breakout level."""
    from app.domain.services.candle_metrics import body as calc_body

    body_size = calc_body(tick.open, tick.high, tick.low, tick.close)
    rng = tick.high - tick.low
    body_pct = body_size / rng if rng > 0 else 0
    if body_pct < 0.5:
        return False
    if direction == "LONG" and tick.close > break_level:
        return True
    if direction == "SHORT" and tick.close < break_level:
        return True
    return False


def nearest_round_number(price: float) -> float:
    """Find nearest round number for MCX instruments."""
    if price < 1000:
        return round(price / 100) * 100
    elif price < 10000:
        return round(price / 500) * 500
    else:
        return round(price / 1000) * 1000


def cluster_aggressive_prints(prints: tuple, cluster_pct: float = 0.001) -> list[float]:
    """Cluster prints within *cluster_pct* of each other, return VWAP of each cluster.

    Caps at top 5 clusters by total volume.
    """
    if not prints:
        return []

    sorted_prints = sorted(prints, key=lambda p: p.price)
    clusters: list[tuple[float, float]] = []
    current_cluster = [(sorted_prints[0].price, sorted_prints[0].volume)]

    for p in sorted_prints[1:]:
        ref_price = current_cluster[0][0]
        if abs(p.price - ref_price) / ref_price <= cluster_pct:
            current_cluster.append((p.price, p.volume))
        else:
            total_vol = sum(v for _, v in current_cluster)
            vwap = sum(pr * v for pr, v in current_cluster) / total_vol
            clusters.append((vwap, total_vol))
            current_cluster = [(p.price, p.volume)]

    if current_cluster:
        total_vol = sum(v for _, v in current_cluster)
        vwap = sum(pr * v for pr, v in current_cluster) / total_vol
        clusters.append((vwap, total_vol))

    clusters.sort(key=lambda c: c[1], reverse=True)
    return [c[0] for c in clusters[:5]]


def extract_bubble_levels_from_footprint(fp_domain: dict | None, min_stacked_count: int = 2) -> list[float]:
    """Extract structural levels from stacked imbalances in footprint data."""
    if not fp_domain:
        return []

    bubble_levels: list[float] = []
    try:
        fp_vals = list(fp_domain.values()) if isinstance(fp_domain, dict) else []
        if not fp_vals:
            return []
        recent_candles = fp_vals[-3:] if len(fp_vals) >= 3 else fp_vals
        for fp_candle in recent_candles:
            if not hasattr(fp_candle, "levels"):
                continue
            for level in fp_candle.levels:
                if getattr(level, "stacked", False):
                    price = getattr(level, "price", 0)
                    if price > 0:
                        bubble_levels.append(price)
    except TypeError:
        pass  # Bubble level extraction error — no bubbles returned
    return bubble_levels


def three_align_check(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    order_book=None,
    ib_high: float = 0.0,
    ib_low: float = 0.0,
    aggressive_levels: list[float] | None = None,
    footprint_domain: dict | None = None,
    return_is_second_drive: bool = False,
    session_info=None,
    tick_size: float = 0.05,
) -> tuple[bool, bool] | tuple[bool, bool, bool]:
    """Three-Align Gate: Market State + Location + Confirmation Bundle.

    FABIO'S RULE: ALL THREE MUST ALIGN.
    1. Market State (BALANCED or IMBALANCED)
    2. Location (price near structural level)
    3. Aggression/Confirmation (volume impulse + delta + spread)

    Returns (gate_passed, confirmation_strong[, is_second_drive]).
    """
    from app.domain.constants import CVD_SLOPE_EXTREME
    from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import check_confirmation_bundle

    # Invalid profile values → block
    if amt_result.poc <= 0 or amt_result.value_area_high <= 0 or amt_result.value_area_low <= 0:
        return (False, False, False) if return_is_second_drive else (False, False)

    # Fabio: Don't trade first 15-30 minutes
    if not min_candles_gate(data):
        logger.debug("Three-Align: blocked by min_candles_gate (session too young)")
        return (False, False, False) if return_is_second_drive else (False, False)

    va_range = amt_result.value_area_high - amt_result.value_area_low
    state_ok = va_range > amt_result.poc * 0.001
    if not state_ok:
        return (False, False, False) if return_is_second_drive else (False, False)

    # CVD Hard Gate
    cvd_slope = getattr(amt_result, "cvd_slope", 0.0)
    if cvd_slope < -CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
        logger.info("Three-Align: BLOCKED — CVD extreme selling (%.0f) in balance", cvd_slope)
        return (False, False, False) if return_is_second_drive else (False, False)
    if cvd_slope > CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
        logger.info("Three-Align: BLOCKED — CVD extreme buying (+%.0f) in balance", cvd_slope)
        return (False, False, False) if return_is_second_drive else (False, False)

    # Near-level check
    near_level = False
    threshold = max(tick_size * 5, va_range * 0.1) if va_range > 0 else tick_size * 5

    levels_to_check: list[float] = [
        amt_result.value_area_high, amt_result.value_area_low, amt_result.poc,
    ]
    if getattr(amt_result, "dev_poc", 0) > 0:
        levels_to_check.extend([amt_result.dev_poc, amt_result.dev_vah, amt_result.dev_val])
    if getattr(amt_result, "leg_poc", 0) > 0:
        levels_to_check.extend([amt_result.leg_poc, amt_result.leg_vah, amt_result.leg_val])
    if getattr(amt_result, "session_vwap", 0) > 0:
        levels_to_check.append(amt_result.session_vwap)
    levels_to_check.extend((amt_result.hvns or [])[:3])
    levels_to_check.extend(getattr(amt_result, "lvns", []) or [])
    if getattr(amt_result, "leg_lvns", []):
        levels_to_check.extend(amt_result.leg_lvns)
    for ib_level in [ib_high, ib_low]:
        if ib_level > 0:
            levels_to_check.append(ib_level)
    if aggressive_levels:
        levels_to_check.extend(aggressive_levels)
    if footprint_domain:
        bubble_levels = extract_bubble_levels_from_footprint(footprint_domain)
        levels_to_check.extend(bubble_levels[:3])
    round_lvl = nearest_round_number(tick.close)
    if round_lvl > 0:
        levels_to_check.append(round_lvl)

    active_level = 0.0
    for level in levels_to_check:
        if level > 0 and abs(tick.close - level) < threshold:
            near_level = True
            active_level = level
            break

    # Second Drive Detection
    is_second_drive = False
    if near_level and data and len(data) > 5:
        history = data[:-1] if data[-1].time == tick.time else data
        recent_touches = 0
        past_touches = 0
        for i, d in enumerate(reversed(history[-30:])):
            dist = min(abs(d.high - active_level), abs(d.low - active_level), abs(d.close - active_level))
            if i < 3:
                if dist < threshold:
                    recent_touches += 1
            else:
                if dist < threshold:
                    past_touches += 1
        if past_touches > 0 and recent_touches == 0:
            is_second_drive = True

    if amt_result.market_state == "IMBALANCED" and near_level and not is_second_drive:
        if abs(cvd_slope) <= 50:
            logger.debug("Three-Align: blocked — first drive only, waiting for re-test")
            return (False, False, False) if return_is_second_drive else (False, False)

    # Confirmation Bundle
    agg_ok = check_confirmation_bundle(data, tick, order_book)
    if not agg_ok:
        logger.debug("Three-Align: blocked — confirmation bundle weak")
        return (False, agg_ok, is_second_drive) if return_is_second_drive else (False, agg_ok)

    gate_passed = state_ok and near_level and agg_ok
    if not return_is_second_drive:
        return gate_passed, agg_ok
    return gate_passed, agg_ok, is_second_drive
