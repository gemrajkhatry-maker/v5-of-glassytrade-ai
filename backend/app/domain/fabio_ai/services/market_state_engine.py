"""Market State Engine — 4-state classification per Fabio AMT spec (FR-04).

States:
  NO_TRADE: Price within ±POC_NO_TRADE_TICKS of POC — dead zone, no edge.
  BALANCED: Price inside VAH–VAL — rotational, mean-reverting.
  IMBALANCED: Price outside VA + displacement + acceptance — trending.
  PROBING: Price outside VA without displacement — unconfirmed break.

Zone sub-classification (within BALANCED):
  NEAR_VAH: Price in upper half of VA (above midpoint)
  NEAR_VAL: Price in lower half of VA (below midpoint)
  NEAR_POC: Price within 10% of VA range from POC

All transitions are logged for audit trail (FR-04-07).
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
) -> MarketStateResult:
    """Fabio's 4-state market state classification (FR-04).

    Priority order:
    1. NO_TRADE — price at POC dead zone (highest priority)
    2. PROBING — price outside VA without displacement
    3. IMBALANCED — price outside VA + displacement + acceptance
    4. BALANCED — price inside VA

    When a displacement leg is active (has_displacement=True or leg_poc > 0),
    the leg's POC/VAH/VAL are used as the primary structural reference instead
    of the session POC/VAH/VAL. This prevents the MR Location rule from
    incorrectly checking against a stale session POC when price is at the
    active leg POC.

    Args:
        price: Current price.
        poc: Point of Control (session).
        vah: Value Area High (session).
        val: Value Area Low (session).
        tick_size: Minimum price increment.
        has_displacement: True if displacement candle detected.
        has_acceptance: True if price acceptance outside VA confirmed.
        balance_ratio: Fraction of recent candles inside VA.
        leg_poc: Leg POC from displacement leg profile (0 if no active leg).
        leg_vah: Leg VAH from displacement leg profile (0 if no active leg).
        leg_val: Leg VAL from displacement leg profile (0 if no active leg).

    Returns:
        MarketStateResult with state, zone, confidence, and trigger.
    """
    # MR Location fix: when a displacement leg is active, the leg's structural
    # levels are the relevant reference — not the stale session levels.
    # Session POC can be 49 pts away while Leg POC is 0.2 pts away.
    _has_active_leg = has_displacement and leg_poc > 0
    effective_poc = leg_poc if _has_active_leg else poc
    effective_vah = leg_vah if (_has_active_leg and leg_vah > 0) else vah
    effective_val = leg_val if (_has_active_leg and leg_val > 0) else val

    poc_distance = abs(price - effective_poc)
    no_trade_zone = tick_size * POC_NO_TRADE_TICKS
    va_range = max(effective_vah - effective_val, tick_size)

    # GATE 3: NO_TRADE — dead zone around effective POC (FR-04-01)
    # When leg is active, checks against leg POC; otherwise session POC.
    if poc_distance <= no_trade_zone:
        poc_label = f"leg POC {effective_poc:.2f}" if _has_active_leg else f"POC {poc:.2f}"
        return MarketStateResult(
            state=MarketState.NO_TRADE,
            zone="NEAR_POC",
            confidence=0.95,
            trigger=f"Price {price:.2f} within {POC_NO_TRADE_TICKS} ticks of {poc_label}",
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
        )

    # Inside effective value area (leg VA when active, session VA otherwise)
    inside_va = effective_val <= price <= effective_vah

    # ── BREAKOUT SENSITIVITY (Approved Fix) ──
    # If price is at the very edge of VA (95%+) and has DISPLACEMENT,
    # pre-emptively classify as PROBING to avoid the "stale BALANCED" lag.
    if inside_va and has_displacement:
        edge_threshold = va_range * 0.05
        at_upper_edge = price > (vah - edge_threshold)
        at_lower_edge = price < (val + edge_threshold)
        if at_upper_edge or at_lower_edge:
            return MarketStateResult(
                state=MarketState.PROBING,
                zone="OUTSIDE_VA" if at_upper_edge else "OUTSIDE_VA",
                confidence=0.70,
                trigger=f"Pre-emptive PROBING: Price {price:.2f} at VA edge with displacement",
                has_displacement=has_displacement,
                has_acceptance=has_acceptance,
                balance_ratio=balance_ratio,
            )

    if inside_va:
        # BALANCED requires price inside VA AND meaningful balance ratio (>30%)
        # prevents "0% in VA (Above ↑)" being classified as BALANCED
        if balance_ratio < 0.30:
            return MarketStateResult(
                state=MarketState.PROBING,
                zone="OUTSIDE_VA",
                confidence=0.55,
                trigger=f"Price {price:.2f} inside VA but balance_ratio {balance_ratio:.0%} < 30% — probing edge",
                has_displacement=has_displacement,
                has_acceptance=has_acceptance,
                balance_ratio=balance_ratio,
            )
        zone = classify_zone(price, effective_poc, effective_vah, effective_val)
        va_label = "leg" if _has_active_leg else "session"
        return MarketStateResult(
            state=MarketState.BALANCED,
            zone=zone,
            confidence=0.80,
            trigger=f"Price {price:.2f} inside {va_label} VA [{effective_val:.2f}, {effective_vah:.2f}] (ratio={balance_ratio:.0%})",
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
        )
    if has_displacement and has_acceptance:
        return MarketStateResult(
            state=MarketState.IMBALANCED,
            zone="OUTSIDE_VA",
            confidence=0.85,
            trigger=f"Price {price:.2f} outside VA with displacement + acceptance",
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
        )

    # Outside VA without displacement = PROBING (FR-04-05)
    return MarketStateResult(
        state=MarketState.PROBING,
        zone="OUTSIDE_VA",
        confidence=0.60,
        trigger=f"Price {price:.2f} outside VA without displacement (unconfirmed)",
        has_displacement=has_displacement,
        has_acceptance=has_acceptance,
        balance_ratio=balance_ratio,
    )


def classify_zone(price: float, poc: float, vah: float, val: float) -> str:
    """Sub-classification within BALANCED state (FR-04-03).

    Returns one of: "NEAR_VAH", "NEAR_VAL", "NEAR_POC"
    """
    va_range = max(vah - val, 1e-9)

    # NEAR_POC: price within 10% of VA range from POC
    if abs(price - poc) <= va_range * 0.10:
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
