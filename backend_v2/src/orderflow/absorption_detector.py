"""
Absorption detector — detect absorption candles.

Dual condition: (high-low) < ATR×0.3 AND volume > avg×2.0
Classify: SELL_ABSORBED → LONG, BUY_ABSORBED → SHORT
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG
from src.core.candle_builder import Candle


@dataclass
class AbsorptionResult:
    """Absorption detection result."""

    detected: bool
    absorption_type: str  # "SELL_ABSORBED", "BUY_ABSORBED", "NONE"


class AbsorptionDetector:
    """
    Detect absorption candles using dual condition.
    """

    @staticmethod
    def detect(
        candle: Candle,
        atr: float,
        avg_vol: float,
    ) -> AbsorptionResult:
        """
        Detect absorption on a candle.

        Conditions:
        1. Candle range < ATR × 0.30
        2. Volume > avg_vol × 2.0

        Args:
            candle: The candle to check
            atr: Current ATR value
            avg_vol: Average volume

        Returns:
            AbsorptionResult with detection status and type.
        """
        if atr <= 0 or avg_vol <= 0:
            return AbsorptionResult(detected=False, absorption_type="NONE")

        # Calculate candle range
        candle_range = candle.high - candle.low

        # Check dual condition
        range_ok = candle_range < atr * CFG.absorption_range_atr
        volume_ok = candle.volume > avg_vol * CFG.absorption_vol_mult

        if not (range_ok and volume_ok):
            return AbsorptionResult(detected=False, absorption_type="NONE")

        # Classify absorption type
        # SELL_ABSORBED: sellers tried to push down but buyers absorbed (delta positive)
        # BUY_ABSORBED: buyers tried to push up but sellers absorbed (delta negative)
        if candle.delta > 0:
            absorption_type = "SELL_ABSORBED"  # Buyers absorbed selling
        elif candle.delta < 0:
            absorption_type = "BUY_ABSORBED"  # Sellers absorbed buying
        else:
            absorption_type = "NEUTRAL"

        return AbsorptionResult(detected=True, absorption_type=absorption_type)