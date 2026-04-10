"""Market State Engine — 4-state Fabio AMT classification.

States (priority order):
1. NO_TRADE — price at POC dead zone
2. PROBING — price outside VA without confirmation
3. IMBALANCED — price outside VA + displacement + acceptance
4. BALANCED — price inside VA
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from appv2.domain.enums.market_state import MarketState
from appv2.config import constants as C

logger = logging.getLogger(__name__)


@dataclass
class MarketStateResult:
    state: MarketState
    zone: str  # "NEAR_VAH" | "NEAR_VAL" | "NEAR_POC" | "OUTSIDE_VA"
    confidence: float  # 0.0–1.0
    trigger: str  # Human-readable reason


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
    """Classify market state per Fabio AMT."""
    poc_distance = abs(price - poc)
    no_trade_zone = tick_size * C.POC_NO_TRADE_TICKS
    va_range = max(vah - val, tick_size)

    # 1. NO_TRADE — dead zone around POC
    if poc_distance <= no_trade_zone:
        return MarketStateResult(
            state=MarketState.NO_TRADE,
            zone="NEAR_POC",
            confidence=0.95,
            trigger=f"Price {price:.2f} within {C.POC_NO_TRADE_TICKS} ticks of POC {poc:.2f}",
        )

    # Pre-emptive PROBING at VA edge with displacement
    if val <= price <= vah and has_displacement:
        edge_threshold = va_range * 0.05
        if price > (vah - edge_threshold) or price < (val + edge_threshold):
            return MarketStateResult(
                state=MarketState.PROBING,
                zone="OUTSIDE_VA",
                confidence=0.70,
                trigger=f"Price at VA edge with displacement — probing",
            )

    # Inside VA
    if val <= price <= vah:
        if balance_ratio < 0.30:
            return MarketStateResult(
                state=MarketState.PROBING,
                zone="OUTSIDE_VA",
                confidence=0.55,
                trigger=f"Inside VA but balance_ratio {balance_ratio:.0%} < 30%",
            )
        zone = _classify_zone(price, poc, vah, val)
        return MarketStateResult(
            state=MarketState.BALANCED,
            zone=zone,
            confidence=0.80,
            trigger=f"Price inside VA [{val:.2f}, {vah:.2f}]",
        )

    # Outside VA
    if has_displacement and has_acceptance:
        return MarketStateResult(
            state=MarketState.IMBALANCED,
            zone="OUTSIDE_VA",
            confidence=0.85,
            trigger=f"Outside VA with displacement + acceptance",
        )

    # Outside VA without confirmation = PROBING
    return MarketStateResult(
        state=MarketState.PROBING,
        zone="OUTSIDE_VA",
        confidence=0.60,
        trigger=f"Outside VA without displacement (unconfirmed)",
    )


def _classify_zone(price: float, poc: float, vah: float, val: float) -> str:
    va_range = max(vah - val, 1e-9)
    if abs(price - poc) <= va_range * 0.10:
        return "NEAR_POC"
    if price > (vah + val) / 2:
        return "NEAR_VAH"
    return "NEAR_VAL"
