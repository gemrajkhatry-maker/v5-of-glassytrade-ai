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
) -> MarketStateResult:
    """Fabio's 4-state market state classification (FR-04).

    Priority order:
    1. NO_TRADE — price at POC dead zone (highest priority)
    2. PROBING — price outside VA without displacement
    3. IMBALANCED — price outside VA + displacement + acceptance
    4. BALANCED — price inside VA

    Args:
        price: Current price.
        poc: Point of Control.
        vah: Value Area High.
        val: Value Area Low.
        tick_size: Minimum price increment.
        has_displacement: True if displacement candle detected.
        has_acceptance: True if price acceptance outside VA confirmed.
        balance_ratio: Fraction of recent candles inside VA.

    Returns:
        MarketStateResult with state, zone, confidence, and trigger.
    """
    poc_distance = abs(price - poc)
    no_trade_zone = tick_size * POC_NO_TRADE_TICKS
    va_range = max(vah - val, tick_size)

    # GATE 3: NO_TRADE — dead zone around POC (FR-04-01)
    if poc_distance <= no_trade_zone:
        return MarketStateResult(
            state=MarketState.NO_TRADE,
            zone="NEAR_POC",
            confidence=0.95,
            trigger=f"Price {price:.2f} within {POC_NO_TRADE_TICKS} ticks of POC {poc:.2f}",
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
        )

    # Inside value area
    inside_va = val <= price <= vah

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
        zone = classify_zone(price, poc, vah, val)
        return MarketStateResult(
            state=MarketState.BALANCED,
            zone=zone,
            confidence=0.80,
            trigger=f"Price {price:.2f} inside VA [{val:.2f}, {vah:.2f}] (ratio={balance_ratio:.0%})",
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
