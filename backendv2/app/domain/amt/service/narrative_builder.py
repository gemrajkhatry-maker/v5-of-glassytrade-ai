"""Narrative building functions for prompts.

Extracted from prompt_builder.py for separation of concerns.
"""

from __future__ import annotations

from typing import Any


def _build_narrative_session_context(data: dict[str, Any]) -> list[str]:
    """Build session context narrative."""
    parts: list[str] = []
    session_name = data.get("session_name", "")
    favor_strategy = data.get("favor_strategy", "")
    if session_name:
        parts.append(f"SESSION: {session_name}.")
    if favor_strategy and favor_strategy != "NEUTRAL":
        active_model = (
            "TREND CONTINUATION"
            if favor_strategy == "TREND_CONTINUATION"
            else "MEAN REVERSION"
        )
        parts.append(f"Session favors: {active_model}.")
    prior_poc = data.get("prior_poc", 0)
    prior_vah = data.get("prior_vah", 0)
    prior_val = data.get("prior_val", 0)
    if prior_poc > 0 and prior_vah > 0 and prior_val > 0:
        parts.append(
            f"PRIOR SESSION: POC {prior_poc:.0f}, VAH {prior_vah:.0f}, VAL {prior_val:.0f}."
        )
    else:
        parts.append(
            "PRIOR SESSION: No historical data — using current session VA only."
        )
    gap_type = data.get("gap_type", "")
    opening_bias = data.get("opening_bias", "")
    if gap_type:
        parts.append(f"Gap: {gap_type}.")
    if opening_bias and opening_bias not in ("NEUTRAL", "IN_BALANCE"):
        parts.append(f"Opening bias: {opening_bias}.")
    ib_high = data.get("ib_high", 0)
    ib_low = data.get("ib_low", 0)
    ib_complete = data.get("ib_complete", False)
    if ib_high > 0 and ib_low > 0 and ib_high != ib_low:
        status = "complete" if ib_complete else "forming"
        ib_range = ib_high - ib_low
        parts.append(
            f"IB ({status}): {ib_low:.2f}-{ib_high:.2f} (range: {ib_range:.2f})."
        )
    elif ib_high > 0 and ib_low > 0:
        parts.append(f"IB (forming): {ib_low:.2f}-{ib_high:.2f} — range expanding")
    return parts


def _build_narrative_market_state(data: dict[str, Any]) -> list[str]:
    """Build market state narrative."""
    from app.domain.trading.model.enums import MarketStateCodec, ProfileShapeCodec
    
    parts: list[str] = []
    price = data.get("ltp", 0)
    vah = data.get("vah", 0)
    val = data.get("val", 0)
    poc = data.get("poc", 0)
    is_balanced = MarketStateCodec.is_balanced(data.get("market_state", "BALANCED"))
    if is_balanced:
        parts.append("MARKET STATE: BALANCED. Active model: MEAN REVERSION.")
        parts.append("Seek: Failed breakout → snap back to POC.")
    else:
        parts.append("MARKET STATE: IMBALANCED. Active model: TREND CONTINUATION.")
        parts.append("Seek: Pullback to LVN → continuation.")
    # ... (rest of the function continues)
    return parts


def _build_narrative_order_flow(data: dict[str, Any]) -> list[str]:
    """Build order flow narrative."""
    parts: list[str] = []
    # Delta and CVD
    delta = data.get("delta", 0)
    cvd_slope = data.get("cvd_slope", 0)
    if delta > 0:
        parts.append(f"DELTA: +{delta:.0f} (net buying pressure).")
    elif delta < 0:
        parts.append(f"DELTA: {delta:.0f} (net selling pressure).")
    if cvd_slope > 0:
        parts.append(f"CVD slope: +{cvd_slope:.0f} (upward momentum).")
    elif cvd_slope < 0:
        parts.append(f"CVD slope: {cvd_slope:.0f} (downward momentum).")
    return parts


def _build_core_amt_narrative(data: dict[str, Any]) -> str:
    """Combine all narrative elements into core AMT narrative."""
    narrative_parts = (
        _build_narrative_session_context(data)
        + _build_narrative_market_state(data)
        + _build_narrative_order_flow(data)
    )
    return "\n".join(narrative_parts)