"""Gate grade scoring for entry confluence."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.domain.constants import CVD_SLOPE_HARD_BLOCK
from app.domain.trading.model.enums import SetupType

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import AMTResult, OHLC

logger = logging.getLogger(__name__)


def _to_float(value, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def check_vwap_bias(
    direction: str,
    price: float,
    vwap: float,
    vwap_upper_2: float,
    vwap_lower_2: float,
) -> dict[str, bool]:
    """Simple VWAP-based warning checks."""
    price_f = _to_float(price, default=0.0) or 0.0
    vwap_f = _to_float(vwap, default=0.0) or 0.0
    vwap_upper_2_f = _to_float(vwap_upper_2, default=0.0) or 0.0
    vwap_lower_2_f = _to_float(vwap_lower_2, default=0.0) or 0.0

    if vwap_f <= 0:
        return {"warning": False, "overextended": False}

    warning = False
    overextended = False
    if direction == "LONG":
        if price_f < vwap_f:
            warning = True
        if vwap_upper_2_f > 0 and price_f >= vwap_upper_2_f:
            overextended = True
    elif direction == "SHORT":
        if price_f > vwap_f:
            warning = True
        if vwap_lower_2_f > 0 and price_f <= vwap_lower_2_f:
            overextended = True
    return {"warning": warning, "overextended": overextended}


def check_imbalance_alignment(direction: str, imbalances: list[Any]) -> int:
    if not imbalances:
        return 0
    aligned = 0
    opposing = 0
    for level in imbalances:
        side = str(getattr(level, "direction", "")).upper()
        if direction == "LONG" and side == "BUY":
            aligned += 1
        elif direction == "SHORT" and side == "SELL":
            aligned += 1
        else:
            opposing += 1
    if aligned > opposing:
        return 1
    if opposing > aligned:
        return -2
    return 0


def compute_grade_score(
    direction: str,
    tick: "OHLC",
    amt_result: "AMTResult",
    setup_type: SetupType | None = None,
    session_phase: str = "",
    favor_strategy: str = "",
    profile_shape: str = "",
    footprint_candle: Any = None,
) -> int:
    """Compute an integer grade score from confluence metrics."""
    score = 0

    cvd_slope = _to_float(getattr(amt_result, "cvd_slope", None), default=0.0) or 0.0
    if direction == "LONG" and cvd_slope < -CVD_SLOPE_HARD_BLOCK:
        logger.warning("Grade hard-kill: LONG blocked by extreme bearish CVD %s", cvd_slope)
        return -10
    if direction == "SHORT" and cvd_slope > CVD_SLOPE_HARD_BLOCK:
        logger.warning("Grade hard-kill: SHORT blocked by extreme bullish CVD %s", cvd_slope)
        return -10

    if (direction == "LONG" and cvd_slope > 0.3) or (direction == "SHORT" and cvd_slope < -0.3):
        score += 1

    if not getattr(amt_result, "cvd_divergence", ""):
        score += 1
    elif (direction == "LONG" and getattr(amt_result, "cvd_divergence", "") == "BEARISH_DIV") or (
        direction == "SHORT" and getattr(amt_result, "cvd_divergence", "") == "BULLISH_DIV"
    ):
        score -= 2

    if (
        favor_strategy == "MEAN_REVERSION"
        and setup_type == SetupType.MEAN_REVERSION
    ) or (
        favor_strategy == "TREND_CONTINUATION"
        and setup_type == SetupType.TREND_MODEL
    ):
        score += 1

    shape_code = profile_shape[0] if profile_shape else ""
    if (shape_code == "b" and direction == "LONG") or (shape_code == "P" and direction == "SHORT"):
        score += 1
    elif (shape_code == "b" and direction == "SHORT") or (shape_code == "P" and direction == "LONG"):
        score -= 1

    price = _to_float(getattr(tick, "close", 0), default=0.0) or 0.0
    session_vwap = _to_float(getattr(amt_result, "session_vwap", 0), default=0.0) or 0.0
    vwap_upper_2 = _to_float(getattr(amt_result, "vwap_upper_2", 0), default=0.0) or 0.0
    vwap_lower_2 = _to_float(getattr(amt_result, "vwap_lower_2", 0), default=0.0) or 0.0
    vwap_check = check_vwap_bias(direction, price, session_vwap, vwap_upper_2, vwap_lower_2)
    if vwap_check["overextended"]:
        score -= 2
    elif vwap_check["warning"]:
        score -= 1

    if footprint_candle and getattr(footprint_candle, "levels", None):
        stacked = [lv for lv in footprint_candle.levels if getattr(lv, "stacked", False)]
        if stacked:
            score += check_imbalance_alignment(direction, stacked)
            has_buy = any(getattr(lv, "delta", 0) > 0 for lv in stacked)
            has_sell = any(getattr(lv, "delta", 0) < 0 for lv in stacked)
            if has_buy and has_sell:
                score -= 3

    if session_phase == "NSE_MIDDAY":
        score -= 1

    return score

