"""Three-Align Gate — Market State + Location + Confirmation.

FABIO'S RULE: ALL THREE MUST ALIGN.
1. Market State (BALANCED or IMBALANCED)
2. Location (price near structural level)
3. Aggression/Confirmation (volume impulse + delta + spread)

Pure, stateless quant functions.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from app.domain.services.candle_metrics import body as calc_body
from app.domain.constants import CVD_SLOPE_EXTREME, D2_CVD_SLOPE_MAX
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import check_confirmation_bundle

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


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


from app.domain.fabio_ai.ports.three_align import ThreeAlignInput


def three_align_check(
    data: list[OHLC],
    amt_result: ThreeAlignInput,
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

    Bug #10 fix: Price velocity acts as a timing qualifier.
    - Extremely high velocity (>0.5 pts/s) → block (whipsaw risk)
    - High velocity (>0.1 pts/s) → pass with reduced confidence
    - Normal/low velocity → no impact

    Returns (gate_passed, confirmation_strong[, is_second_drive]).
    """

    # Invalid profile values → block
    poc = amt_result.poc
    vah = amt_result.value_area_high
    val = amt_result.value_area_low
    if poc is None or vah is None or val is None or poc <= 0 or vah <= 0 or val <= 0:
        return (False, False, False) if return_is_second_drive else (False, False)

    # Guard against NaN/inf
    if not (poc and vah and val):
        if not (math.isfinite(poc) and math.isfinite(vah) and math.isfinite(val)):
            return (False, False, False) if return_is_second_drive else (False, False)

    va_range = vah - val
    state_ok = va_range > poc * 0.001
    if not state_ok:
        return (False, False, False) if return_is_second_drive else (False, False)

    # CVD Hard Gate
    cvd_slope = amt_result.cvd_slope
    if cvd_slope is not None and not math.isfinite(cvd_slope):
        cvd_slope = None
    cvd_div = amt_result.cvd_divergence
    
    # CVD DIVERGENCE: When divergence is detected, it counts as strong confirmation.
    # A divergence (price breaking one way, CVD going the other) IS itself a signal.
    divergence_confirmation = bool(cvd_div and cvd_div != "")
    
    if cvd_slope is not None and cvd_slope < -CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
        logger.info("Three-Align: BLOCKED — CVD extreme selling (%.0f) in balance", cvd_slope)
        return (False, False, False) if return_is_second_drive else (False, False)
    if cvd_slope is not None and cvd_slope > CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
        logger.info("Three-Align: BLOCKED — CVD extreme buying (+%.0f) in balance", cvd_slope)
        return (False, False, False) if return_is_second_drive else (False, False)

    # Price Velocity Timing Qualifier (Bug #10)
    price_velocity = amt_result.price_velocity
    if price_velocity is not None and not math.isfinite(price_velocity):
        price_velocity = None
    price_velocity = abs(price_velocity or 0.0)
    if price_velocity > 0.5:
        logger.info(
            "Three-Align: BLOCKED — price velocity too high (%.3f pts/s), whipsaw risk",
            price_velocity,
        )
        return (False, False, False) if return_is_second_drive else (False, False)
    elif price_velocity > 0.1:
        logger.debug(
            "Three-Align: velocity elevated (%.3f pts/s), gate proceeds with reduced confidence",
            price_velocity,
        )

    # Near-level check
    near_level = False
    # Increased threshold for options: 8 ticks (was 5) or 15% of VA range (was 10%)
    # This allows price 6+ points from POC to still qualify as "near" for NIFTY options
    threshold = max(tick_size * 8, va_range * 0.15) if va_range > 0 else tick_size * 8

    # MR Location: context-aware POC selection.
    # PROBING/IMBALANCED + active leg → leg_poc is the structural reference for the
    # current auction leg and should be checked first.
    # BALANCED → session POC/VAH/VAL remain the primary reference.
    _leg_poc = amt_result.leg_poc
    _leg_vah = amt_result.leg_vah
    _leg_val = amt_result.leg_val
    _use_leg_poc_first = (
        amt_result.market_state in ("PROBING", "IMBALANCED")
        and _leg_poc is not None and _leg_poc > 0
    )

    if _use_leg_poc_first:
        # Leg levels first — they represent the active auction structure
        levels_to_check: list[float] = [_leg_poc, _leg_vah, _leg_val]
        # Session levels still checked as secondary reference
        levels_to_check.extend([vah, val, poc])
        logger.debug(
            "Three-Align MR Location: using leg_poc=%.2f as primary (state=%s)",
            _leg_poc, amt_result.market_state,
        )
    else:
        levels_to_check: list[float] = [vah, val, poc]

    if amt_result.dev_poc is not None and amt_result.dev_poc > 0:
        levels_to_check.extend([amt_result.dev_poc, amt_result.dev_vah, amt_result.dev_val])
    # When leg_poc is NOT used as primary (BALANCED state), still append it as secondary
    if not _use_leg_poc_first and _leg_poc is not None and _leg_poc > 0:
        levels_to_check.extend([_leg_poc, _leg_vah, _leg_val])
    if amt_result.session_vwap is not None and amt_result.session_vwap > 0:
        levels_to_check.append(amt_result.session_vwap)
    if amt_result.hvns:
        levels_to_check.extend((amt_result.hvns or [])[:3])
    if amt_result.lvns:
        levels_to_check.extend(amt_result.lvns or [])
    if amt_result.leg_lvns:
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
        if level is not None and level > 0 and abs(tick.close - level) < threshold:
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
            d_high = _to_float(getattr(d, "high", None), default=None)
            d_low = _to_float(getattr(d, "low", None), default=None)
            d_close = _to_float(getattr(d, "close", None), default=None)
            if d_high is None or d_low is None or d_close is None:
                continue
            dist = min(
                abs(d_high - active_level),
                abs(d_low - active_level),
                abs(d_close - active_level),
            )
            if i < 3:
                if dist < threshold:
                    recent_touches += 1
            else:
                if dist < threshold:
                    past_touches += 1
        if past_touches > 0 and recent_touches == 0:
            is_second_drive = True

    # Fabio: First drive IS valid entry with aggression confirmation
    # Removed the block that prevented first drive entries
    # The code below was blocking first drive in IMBALANCED state - WRONG
    # if amt_result.market_state == "IMBALANCED" and near_level and not is_second_drive:
    #     if abs(cvd_slope) <= D2_CVD_SLOPE_MAX:
    #         logger.debug("Three-Align: blocked — first drive only, waiting for re-test")
    #         return (False, False, False) if return_is_second_drive else (False, False)

    # Confirmation Bundle
    agg_ok = check_confirmation_bundle(data, tick, order_book)
    
    # CVD divergence counts as strong confirmation override
    confirmation_strong = agg_ok or divergence_confirmation
    
    if not confirmation_strong:
        logger.debug("Three-Align: blocked — confirmation bundle weak")
        return (False, False, False) if return_is_second_drive else (False, False)

    gate_passed = state_ok and near_level and confirmation_strong
    if not return_is_second_drive:
        return gate_passed, confirmation_strong
    return gate_passed, confirmation_strong, is_second_drive
