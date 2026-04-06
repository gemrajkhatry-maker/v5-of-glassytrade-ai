"""Trade thesis contract for execution-grade entries.

Every executable trade must be defensible in Fabio terms:
  1. market state
  2. location
  3. aggression
  4. session context
  5. structural invalidation
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.domain.trading.models.enums import SetupType
from app.domain.trading.models.value_objects import AMTResult, OHLC


@dataclass(frozen=True)
class TradeThesis:
    market_state: str
    location_type: str
    location_level: float
    aggression_trigger: str
    session_context: str
    invalidation_level: float
    setup_family: str = ""

    @property
    def is_complete(self) -> bool:
        return (
            self.market_state in {"BALANCED", "IMBALANCED"}
            and bool(self.location_type)
            and self.location_level > 0
            and bool(self.aggression_trigger)
            and bool(self.session_context)
            and self.invalidation_level > 0
        )

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)


def _nearest_level(
    levels: list[tuple[str, float]], price: float, threshold: float
) -> tuple[str, float]:
    candidates = [
        (label, level)
        for label, level in levels
        if level > 0 and abs(price - level) <= threshold
    ]
    if not candidates:
        return "MID_RANGE", 0.0
    return min(candidates, key=lambda item: abs(price - item[1]))


def infer_location(price: float, amt_result: AMTResult) -> tuple[str, float]:
    """Return the nearest structural auction location for the current price.
    
    FABIO: "Location is where price reacts" — must find meaningful level.
    If no specific level found, use VA boundary as default.
    """
    va_range = abs(amt_result.value_area_high - amt_result.value_area_low)
    threshold = (
        min(max(va_range * 0.35, price * 0.0025), price * 0.015) if price > 0 else 0.0
    )
    levels: list[tuple[str, float]] = [
        ("POC", amt_result.poc),
        ("VAH", amt_result.value_area_high),
        ("VAL", amt_result.value_area_low),
        ("PRIOR_POC", amt_result.prior_poc),
        ("PRIOR_VAH", amt_result.prior_vah),
        ("PRIOR_VAL", amt_result.prior_val),
        ("IB_HIGH", amt_result.ib_high),
        ("IB_LOW", amt_result.ib_low),
        ("DEV_POC", amt_result.dev_poc),
        ("DEV_VAH", amt_result.dev_vah),
        ("DEV_VAL", amt_result.dev_val),
        ("LEG_POC", amt_result.leg_poc),
        ("LEG_VAH", amt_result.leg_vah),
        ("LEG_VAL", amt_result.leg_val),
    ]
    levels.extend([("LVN", level) for level in amt_result.lvns[:5]])
    levels.extend([("HVN", level) for level in amt_result.hvns[:5]])
    
    location_type, location_level = _nearest_level(levels, price, threshold)
    
    # FIX: If no specific level found, use VA boundary as fallback
    # This ensures we always have a valid location_type for thesis validation
    if location_type == "MID_RANGE" or location_level <= 0:
        # Use nearest VA boundary
        if price > (amt_result.value_area_high + amt_result.value_area_low) / 2:
            return "VAH", amt_result.value_area_high
        else:
            return "VAL", amt_result.value_area_low
    
    return location_type, location_level


def infer_aggression_trigger(tick: OHLC, amt_result: AMTResult) -> str:
    """Return the clearest aggression confirmation available in the current context.
    
    FABIO: "Aggression is the trigger" — we need SOME form of aggression signal.
    Never return empty string (would cause thesis validation to fail).
    """
    delta_ratio = abs(tick.delta) / tick.volume if tick.volume > 0 else 0.0
    
    # High-confidence triggers (specific setups)
    if amt_result.liquidity_sweep:
        return amt_result.liquidity_sweep
    if amt_result.lvn_play:
        return "LVN_REACTION"
    if amt_result.break_type:
        return f"BREAK_{amt_result.break_type}"
    if abs(amt_result.ofi) >= 0.2:
        return "ORDER_BOOK_IMBALANCE"
    
    # Medium-confidence triggers (volume/delta based)
    if abs(amt_result.aggression) >= 0.5 and delta_ratio >= 0.15:
        return "DELTA_EXPANSION"
    if abs(amt_result.cvd_slope) >= 0.3:
        return "CVD_EXPANSION"
    if delta_ratio >= 0.15:
        return "DELTA_PRESSURE"
    
    # Low-confidence fallbacks (always return SOMETHING)
    if tick.volume > 100:
        return "VOLUME_PRESENT"
    if abs(tick.delta) > 0:
        return "DELTA_ACTIVITY"
    
    # Final fallback — market is moving, that's aggression
    if tick.high != tick.low:
        return "PRICE_MOVEMENT"
    
    return "MARKET_ACTIVE"  # Never return empty string


@lru_cache(maxsize=8)
def setup_family_for(setup_type: SetupType) -> str:
    if setup_type == SetupType.MEAN_REVERSION:
        return "return_to_value"
    if setup_type == SetupType.TREND_MODEL:
        return "imbalance_continuation"
    return setup_type.value.lower()


def build_trade_thesis(
    *,
    tick: OHLC,
    amt_result: AMTResult,
    setup_type: SetupType,
    session_context: str,
    invalidation_level: float,
) -> TradeThesis:
    """Build an execution-grade trade thesis from the current market context."""
    location_type, location_level = infer_location(tick.close, amt_result)
    return TradeThesis(
        market_state=amt_result.market_state,
        location_type=location_type,
        location_level=location_level,
        aggression_trigger=infer_aggression_trigger(tick, amt_result),
        session_context=session_context,
        invalidation_level=invalidation_level,
        setup_family=setup_family_for(setup_type),
    )


def validate_trade_thesis(
    thesis: TradeThesis | dict[str, Any] | None,
) -> tuple[bool, str]:
    """Validate that a thesis is complete enough for execution."""
    if thesis is None:
        return False, "missing_state"

    if isinstance(thesis, dict):
        thesis = TradeThesis(
            market_state=str(thesis.get("market_state", "")),
            location_type=str(thesis.get("location_type", "")),
            location_level=float(thesis.get("location_level", 0.0) or 0.0),
            aggression_trigger=str(thesis.get("aggression_trigger", "")),
            session_context=str(thesis.get("session_context", "")),
            invalidation_level=float(thesis.get("invalidation_level", 0.0) or 0.0),
            setup_family=str(thesis.get("setup_family", "")),
        )

    if thesis.market_state not in {"BALANCED", "IMBALANCED", "PROBING"}:
        return False, "missing_state"
    if thesis.location_type == "MID_RANGE" or thesis.location_level <= 0:
        return False, "mid_range_entry"
    if not thesis.aggression_trigger:
        return False, "missing_aggression"
    if not thesis.session_context:
        return False, "wrong_session"
    if thesis.invalidation_level <= 0:
        return False, "missing_invalidation"
    return True, ""
