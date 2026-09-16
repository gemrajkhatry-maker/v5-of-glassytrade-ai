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

from quant.contracts.enums import MarketState
from quant.contracts.constants import (
    BALANCE_RATIO_THRESHOLD,
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
    inside_session_va = val <= price <= vah
    is_extreme = vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) >= 3.0

    # If there is active displacement OR price is outside session Value Area OR low balance -> IMBALANCED
    if has_displacement or not inside_session_va or balance_ratio < BALANCE_RATIO_THRESHOLD:
        trigger_parts = []
        conf = 0.5  # base confidence for imbalanced
        if has_displacement:
            trigger_parts.append("active displacement leg")
            conf += 0.25
        if not inside_session_va:
            trigger_parts.append(f"outside session VA [{val:.2f}, {vah:.2f}]")
            conf += 0.20
        if balance_ratio < BALANCE_RATIO_THRESHOLD:
            trigger_parts.append(f"low balance ratio ({balance_ratio:.2f})")
            conf += 0.10
        if has_acceptance:
            conf += 0.05
        if is_extreme:
            conf += 0.05

        zone = "OUTSIDE_VA" if not inside_session_va else "DISPLACEMENT"
        return MarketStateResult(
            state=MarketState.IMBALANCED,
            zone=zone,
            confidence=min(conf, 0.95),
            trigger=f"Price {price:.2f} " + ", ".join(trigger_parts),
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
            is_extreme_deviation=is_extreme,
        )

    # Price inside session VA, no displacement, high balance ratio -> BALANCED
    zone = classify_zone(price, poc, vah, val)
    conf = 0.55  # base confidence for balanced
    if balance_ratio >= BALANCE_RATIO_THRESHOLD:
        conf += 0.20
    if has_acceptance:
        conf += 0.10
    if zone == "NEAR_POC":
        conf += 0.10
    elif zone in ("NEAR_VAH", "NEAR_VAL"):
        conf += 0.05
    if is_extreme:
        conf -= 0.15  # extreme deviation reduces confidence in balance

    return MarketStateResult(
        state=MarketState.BALANCED,
        zone=zone,
        confidence=max(0.30, min(conf, 0.90)),
        trigger=f"Price {price:.2f} inside session VA [{val:.2f}, {vah:.2f}]",
        has_displacement=has_displacement,
        has_acceptance=has_acceptance,
        balance_ratio=balance_ratio,
        is_extreme_deviation=is_extreme,
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
