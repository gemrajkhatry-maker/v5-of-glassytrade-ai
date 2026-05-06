"""Grading — A/B/C setup grade classification from market confluence.

Computes an integer score from:
- CVD direction alignment
- Session / setup alignment
- Profile shape alignment
- VWAP bias
- Stacked imbalance alignment

Score >= 3  → A-grade,  0-2 → B-grade,  < 0 → C-grade
-10 = hard kill (extreme CVD opposition)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.constants import CVD_SLOPE_HARD_BLOCK
from app.domain.trading.models.enums import SetupType

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


def check_vwap_bias(
    direction: str,
    price: float,
    vwap: float,
    vwap_upper_2: float,
    vwap_lower_2: float,
) -> dict:
    """Check VWAP bias for entry quality.

    Returns {"warning": bool, "overextended": bool}.
    """
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


def check_imbalance_alignment(direction: str, imbalances: list) -> int:
    """Grade adjustment based on stacked imbalance alignment.

    +1 if aligned (majority imbalances support direction),
    -2 if opposing (majority imbalances oppose direction),
     0 if empty or evenly mixed.
    """
    if not imbalances:
        return 0
    aligned = sum(
        1
        for im in imbalances
        if (direction == "LONG" and im.direction == "BUY")
        or (direction == "SHORT" and im.direction == "SELL")
    )
    opposing = len(imbalances) - aligned
    if aligned > opposing:
        return 1
    if opposing > aligned:
        return -2
    return 0


def _to_float(value, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_grade_score(
    direction: str,
    tick: OHLC,
    amt_result: AMTResult,
    setup_type=None,  # SetupType
    session_phase: str = "",
    favor_strategy: str = "",
    profile_shape: str = "",
    footprint_candle=None,
) -> int:
    """Compute A/B/C setup grade score from market confluence."""

    score = 0

    # HARD GATE: Extreme CVD Opposition
    cvd_slope = _to_float(amt_result.cvd_slope, default=None)
    if cvd_slope is None:
        cvd_slope = 0.0
    if direction == "LONG" and cvd_slope < -CVD_SLOPE_HARD_BLOCK:
        logger.warning(
            "Grade score killed (CVD Hard Gate): LONG blocked due to extreme bearish CVD (%s)",
            cvd_slope,
        )
        return -10
    if direction == "SHORT" and cvd_slope > CVD_SLOPE_HARD_BLOCK:
        logger.warning(
            "Grade score killed (CVD Hard Gate): SHORT blocked due to extreme bullish CVD (%s)",
            cvd_slope,
        )
        return -10

    # CVD confirms direction
    if (direction == "LONG" and cvd_slope > 0.3) or (
        direction == "SHORT" and cvd_slope < -0.3
    ):
        score += 1
    # No CVD divergence against direction
    if not amt_result.cvd_divergence:
        score += 1
    elif (direction == "LONG" and amt_result.cvd_divergence == "BEARISH_DIV") or (
        direction == "SHORT" and amt_result.cvd_divergence == "BULLISH_DIV"
    ):
        score -= 2

    # Session / setup alignment
    if (
        favor_strategy == "MEAN_REVERSION" and setup_type == SetupType.MEAN_REVERSION
    ) or (
        favor_strategy == "TREND_CONTINUATION" and setup_type == SetupType.TREND_MODEL
    ):
        score += 1

    # Profile shape alignment
    shape_code = profile_shape[0] if profile_shape else ""
    if (shape_code == "b" and direction == "LONG") or (
        shape_code == "P" and direction == "SHORT"
    ):
        score += 1
    elif (shape_code == "b" and direction == "SHORT") or (
        shape_code == "P" and direction == "LONG"
    ):
        score -= 1

    # VWAP bias
    tick_vwap = _to_float(getattr(tick, "vwap", 0), default=0.0)
    session_vwap = _to_float(getattr(amt_result, "session_vwap", 0), default=0.0)
    vwap = session_vwap if (session_vwap is not None and session_vwap > 0) else ((tick_vwap or 0.0) if (tick_vwap is not None and tick_vwap > 0) else 0.0)
    vwap = _to_float(vwap, default=0.0) or 0.0
    price = _to_float(tick.close, default=0.0) or 0.0
    vwap_upper_2 = _to_float(getattr(amt_result, "vwap_upper_2", 0), default=0.0) or 0.0
    vwap_lower_2 = _to_float(getattr(amt_result, "vwap_lower_2", 0), default=0.0) or 0.0
    vwap_check = check_vwap_bias(
        direction,
        price,
        vwap,
        vwap_upper_2,
        vwap_lower_2,
    )
    if vwap_check.get("overextended"):
        score -= 2
    elif vwap_check.get("warning"):
        score -= 1

    # Stacked imbalance alignment from footprint
    if (
        footprint_candle
        and hasattr(footprint_candle, "levels")
        and footprint_candle.levels
    ):
        stacked = [
            lv for lv in footprint_candle.levels if getattr(lv, "stacked", False)
        ]
        if stacked:
            score += check_imbalance_alignment(direction, stacked)
            has_buy = any(lv.delta > 0 for lv in stacked)
            has_sell = any(lv.delta < 0 for lv in stacked)
            if has_buy and has_sell:
                score -= 3

    # Midday downgrade
    if session_phase == "NSE_MIDDAY":
        score -= 1

    return score
