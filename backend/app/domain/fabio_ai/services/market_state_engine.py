"""Market State Engine — 2-state classification per Fabio AMT spec.

States:
  BALANCED: Price inside VAH–VAL — rotational, mean-reverting.
  IMBALANCED: Price outside VA + displacement + acceptance — trending.

Zone sub-classification (within BALANCED):
  NEAR_VAH: Price in upper half of VA (above midpoint)
  NEAR_VAL: Price in lower half of VA (below midpoint)
  NEAR_POC: Price within 10% of VA range from POC

All transitions are logged for audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.trading.models.enums import MarketState
from app.domain.constants import (
    POC_NO_TRADE_TICKS,
    BALANCE_RATIO_THRESHOLD,
    DISPLACEMENT_MULTIPLIER,
)

logger = logging.getLogger(__name__)


@dataclass
class MarketStateResult:
    """Result of market state detection."""

    state: MarketState
    zone: str  # "NEAR_VAH" | "NEAR_VAL" | "NEAR_POC" | "OUTSIDE_VA" | ""
    confidence: float  # 0.0-1.0
    trigger: str  # Why this state was selected
    has_displacement: bool
    has_acceptance: bool
    balance_ratio: float
    is_extreme_deviation: bool = False  # True if > 3.0 sigma


def detect_market_state(
    price: float,
    poc: float,
    vah: float,
    val: float,
    tick_size: float,
    has_displacement: bool,
    has_acceptance: bool,
    balance_ratio: float = 0.0,
    leg_poc: float = 0.0,
    leg_vah: float = 0.0,
    leg_val: float = 0.0,
    vwap_deviation_sigmas: float | None = None,
    ib_break_direction: str = "",  # "UP" / "DOWN" / ""
    ib_complete: bool = False,
    ib_high: float = 0.0,
    ib_low: float = 0.0,
) -> MarketStateResult:
    """Fabio's 2-state market state classification.

    Priority order:
    1. BALANCED — price inside VA with acceptance
    2. IMBALANCED — price outside VA OR displacement+acceptance
    """
    _has_active_leg = has_displacement and leg_poc > 0
    effective_poc = leg_poc if _has_active_leg else poc
    effective_vah = leg_vah if (_has_active_leg and leg_vah > 0) else vah
    effective_val = leg_val if (_has_active_leg and leg_val > 0) else val

    va_range = max(effective_vah - effective_val, tick_size)
    is_extreme = vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) >= 3.0

    # Inside effective value area (leg VA when active, session VA otherwise)
    inside_va = effective_val <= price <= effective_vah

    if inside_va and balance_ratio >= 0.5:
        zone = classify_zone(price, effective_poc, effective_vah, effective_val)
        va_label = "leg" if _has_active_leg else "session"
        return MarketStateResult(
            state=MarketState.BALANCED,
            zone=zone,
            confidence=0.80,
            trigger=f"Price {price:.2f} inside {va_label} VA [{effective_val:.2f}, {effective_vah:.2f}]",
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
            is_extreme_deviation=is_extreme
        )
    
    # Outside VA OR displacement+acceptance = IMBALANCED
    trigger_parts = []
    if not inside_va:
        trigger_parts.append(f"outside VA [{effective_val:.2f}, {effective_vah:.2f}]")
    if has_displacement and has_acceptance:
        trigger_parts.append("displacement + acceptance")
    
    return MarketStateResult(
        state=MarketState.IMBALANCED,
        zone="OUTSIDE_VA",
        confidence=0.85,
        trigger=f"Price {price:.2f} " + ", ".join(trigger_parts),
        has_displacement=has_displacement,
        has_acceptance=has_acceptance,
        balance_ratio=balance_ratio,
        is_extreme_deviation=is_extreme
    )


def classify_zone(price: float, poc: float, vah: float, val: float) -> str:
    """Sub-classification within BALANCED state (FR-04-03).

    Returns one of: "NEAR_VAH", "NEAR_VAL", "NEAR_POC"
    """
    va_range = max(vah - val, 1e-9)

    # NEAR_POC: price within 5% of VA range from POC (Tightened from 10% per 3PM bug report)
    if abs(price - poc) <= va_range * 0.05:
        return "NEAR_POC"

    # Upper half = NEAR_VAH
    mid_va = (vah + val) / 2
    if price > mid_va:
        return "NEAR_VAH"

    return "NEAR_VAL"


def log_state_transition(
    previous: MarketState | None,
    current: MarketState,
    result: MarketStateResult,
) -> None:
    """Log state transition for audit trail (FR-04-07)."""
    if previous is None or previous != current:
        logger.info(
            "Market state: %s → %s | zone=%s conf=%.0f%% trigger=%s",
            previous.value if previous else "INIT",
            current.value,
            result.zone,
            result.confidence * 100,
            result.trigger,
        )
