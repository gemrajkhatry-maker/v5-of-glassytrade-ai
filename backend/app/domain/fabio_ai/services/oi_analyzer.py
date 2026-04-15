"""OI Pressure Analyzer — detects open-interest walls at option strikes.

Fabio Gap #5: Compare current strike OI vs surrounding strikes (±200, ±100).
HIGH OI walls (≥3.0x surrounding avg) reduce confidence but don't block trades.
MEDIUM OI walls (≥1.5x) apply a smaller confidence reduction.
LOW OI pressure has no effect.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.ports.market_data import IMarketData

logger = logging.getLogger(__name__)


class OIPressureLevel(str, Enum):
    """Classification of OI pressure at a strike."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class OIPressureResult:
    """Result of OI pressure analysis for a strike."""
    pressure: OIPressureLevel
    ratio: float
    current_oi: int
    avg_surrounding_oi: float
    confidence_multiplier: float
    signal: str  # "RESISTANCE", "CAUTION", "CLEAR"

    @property
    def is_wall(self) -> bool:
        """True if this strike represents a significant OI wall."""
        return self.pressure in (OIPressureLevel.HIGH, OIPressureLevel.MEDIUM)


# OI pressure thresholds
OI_HIGH_RATIO = 3.0  # ≥3.0x surrounding avg = HIGH pressure
OI_MEDIUM_RATIO = 1.5  # ≥1.5x surrounding avg = MEDIUM pressure

# Confidence multipliers (reduce confidence, not block)
OI_HIGH_CONFIDENCE_MULT = 0.6  # HIGH pressure → 60% of original confidence
OI_MEDIUM_CONFIDENCE_MULT = 0.85  # MEDIUM pressure → 85% of original confidence
OI_LOW_CONFIDENCE_MULT = 1.0  # LOW pressure → no reduction

# Surrounding strike offsets to compare against
SURROUNDING_OFFSETS = [-200, -100, 100, 200]


class OIAnalyzer:
    """Calculates OI pressure at option strikes.

    Injects IMarketData to fetch option chain data.
    Pure domain logic — no I/O side effects beyond the injected port.
    """

    def __init__(self, market_data: "IMarketData | None" = None) -> None:
        self._market_data = market_data

    def check_oi_pressure(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        oi_data: dict | None = None,
    ) -> "OIPressureResult":
        """Compare current strike OI vs surrounding strikes.

        Args:
            symbol: Underlying symbol (e.g. "CRUDEOIL").
            strike: The strike price to analyze.
            option_type: "CE" or "PE".
            oi_data: Pre-fetched option chain dict (strike -> {CE/PE -> {oi: int}}).
                     If None, fetches from market_data port.

        Returns:
            OIPressureResult with pressure classification and confidence multiplier.
        """
        if oi_data is None:
            if self._market_data is None:
                return self._default_result()
            chain = self._market_data.get_option_chain(symbol)
            if chain is None:
                return self._default_result()
            oi_data = chain

        current_oi = self._extract_oi(oi_data, strike, option_type)

        surrounding_oi_values = []
        for offset in SURROUNDING_OFFSETS:
            surrounding_strike = strike + offset
            oi_val = self._extract_oi(oi_data, surrounding_strike, option_type)
            if oi_val > 0:
                surrounding_oi_values.append(oi_val)

        avg_surrounding = (
            sum(surrounding_oi_values) / len(surrounding_oi_values)
            if surrounding_oi_values
            else 1.0
        )

        ratio = current_oi / avg_surrounding if avg_surrounding > 0 else 1.0

        if ratio >= OI_HIGH_RATIO:
            pressure = OIPressureLevel.HIGH
            confidence_mult = OI_HIGH_CONFIDENCE_MULT
            signal = "RESISTANCE"
        elif ratio >= OI_MEDIUM_RATIO:
            pressure = OIPressureLevel.MEDIUM
            confidence_mult = OI_MEDIUM_CONFIDENCE_MULT
            signal = "CAUTION"
        else:
            pressure = OIPressureLevel.LOW
            confidence_mult = OI_LOW_CONFIDENCE_MULT
            signal = "CLEAR"

        logger.debug(
            "OI pressure for %s %s @ %.0f: current_oi=%d, avg_surrounding=%.0f, "
            "ratio=%.2f, pressure=%s, signal=%s",
            symbol, option_type, strike,
            current_oi, avg_surrounding, ratio,
            pressure.value, signal,
        )

        return OIPressureResult(
            pressure=pressure,
            ratio=round(ratio, 2),
            current_oi=current_oi,
            avg_surrounding_oi=round(avg_surrounding, 0),
            confidence_multiplier=confidence_mult,
            signal=signal,
        )

    def apply_confidence_reduction(
        self,
        base_confidence: float,
        oi_result: "OIPressureResult",
    ) -> float:
        """Apply OI-based confidence reduction to a base confidence score.

        Args:
            base_confidence: Original confidence (0.0 - 1.0).
            oi_result: Result from check_oi_pressure().

        Returns:
            Adjusted confidence score.
        """
        adjusted = base_confidence * oi_result.confidence_multiplier
        return round(max(0.0, min(1.0, adjusted)), 4)

    @staticmethod
    def _extract_oi(oi_data: dict, strike: float, option_type: str) -> int:
        """Extract OI value from option chain data for a given strike/type."""
        strike_data = oi_data.get(strike, {})
        if not isinstance(strike_data, dict):
            return 0
        type_data = strike_data.get(option_type, {})
        if not isinstance(type_data, dict):
            return 0
        oi_val = type_data.get("oi", 0)
        return int(oi_val) if oi_val else 0

    @staticmethod
    def _default_result() -> "OIPressureResult":
        """Return a default LOW pressure result when no data is available."""
        return OIPressureResult(
            pressure=OIPressureLevel.LOW,
            ratio=1.0,
            current_oi=0,
            avg_surrounding_oi=0,
            confidence_multiplier=OI_LOW_CONFIDENCE_MULT,
            signal="CLEAR",
        )
