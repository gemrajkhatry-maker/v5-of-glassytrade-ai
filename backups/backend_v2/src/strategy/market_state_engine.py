"""
Market state engine — 4-state classification with zone sub-classification.

States: NO_TRADE, BALANCED, IMBALANCED, PROBING
Zones: NEAR_VAH, NEAR_VAL, NEAR_POC, EMPTY
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG


@dataclass
class MarketStateResult:
    """Market state detection result."""

    state: str  # NO_TRADE, BALANCED, IMBALANCED, PROBING
    zone: str  # NEAR_VAH, NEAR_VAL, NEAR_POC, EMPTY


class MarketStateEngine:
    """
    Market state classification per Fabio's AMT methodology.

    Uses static methods for pure function behavior.
    """

    @staticmethod
    def detect(
        price: float,
        poc: Optional[float],
        vah: Optional[float],
        val: Optional[float],
        tick_size: float,
        has_displacement: bool,
        has_acceptance: bool,
    ) -> MarketStateResult:
        """
        Detect current market state.

        Args:
            price: Current price
            poc: Point of Control
            vah: Value Area High
            val: Value Area Low
            tick_size: Instrument tick size
            has_displacement: Whether displacement candle detected
            has_acceptance: Whether acceptance detected outside VA

        Returns:
            MarketStateResult with state and zone.
        """
        if poc is None or vah is None or val is None:
            return MarketStateResult(state="OUTSIDE", zone="EMPTY")

        # GATE 3: NO_TRADE — dead zone around POC (±2 ticks)
        poc_distance = abs(price - poc)
        poc_dead_zone = tick_size * CFG.poc_no_trade_ticks

        if poc_distance <= poc_dead_zone:
            zone = MarketStateEngine.classify_zone(price, poc, vah, val)
            return MarketStateResult(state="NO_TRADE", zone=zone)

        # Inside value area
        if val <= price <= vah:
            zone = MarketStateEngine.classify_zone(price, poc, vah, val)
            return MarketStateResult(state="BALANCED", zone=zone)

        # Outside VA with displacement + acceptance
        if has_displacement and has_acceptance:
            zone = "EMPTY"
            return MarketStateResult(state="IMBALANCED", zone=zone)

        # Outside VA without displacement = PROBING
        zone = "EMPTY"
        return MarketStateResult(state="PROBING", zone=zone)

    @staticmethod
    def classify_zone(
        price: float,
        poc: float,
        vah: float,
        val: float,
    ) -> str:
        """
        Sub-classify within BALANCED state.

        Args:
            price: Current price
            poc: Point of Control
            vah: Value Area High
            val: Value Area Low

        Returns:
            Zone string: NEAR_VAH, NEAR_VAL, or NEAR_POC.
        """
        mid_va = (vah + val) / 2
        poc_proximity = (vah - val) * 0.1

        if abs(price - poc) <= poc_proximity:
            return "NEAR_POC"
        elif price > mid_va:
            return "NEAR_VAH"
        else:
            return "NEAR_VAL"

    @staticmethod
    def is_tradeable(state: str) -> bool:
        """
        Check if market state allows trading.

        Only BALANCED and IMBALANCED are tradeable.
        """
        return state in ("BALANCED", "IMBALANCED")