"""Absorption Validator — Forward-looking displacement validation per Fabio AMT spec.

High volume + zero range = Absorption. But without immediate subsequent price
displacement (range expansion), it's just exhaustion/fake absorption.

Usage:
    validator = AbsorptionValidator()
    validator.record_absorption(candle)
    result = validator.validate_displacement(next_candle, next2_candle)
    if result.valid:
        # Confirmed absorption with displacement
        return Signal(..., reason="Confirmed absorption with displacement")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass
class AbsorptionValidationResult:
    """Result of absorption displacement validation."""
    valid: bool
    direction: str  # "LONG" | "SHORT" | ""
    displacement_confirmed: bool
    reason: str


class AbsorptionValidator:
    """Forward-looking absorption displacement validator.

    Per Fabio: "High volume + zero range = Absorption. But without immediate
    subsequent price displacement (range expansion), it's just exhaustion."

    An absorption candle must be followed by price displacement (range expansion)
    in the next 1-2 candles to confirm it as a valid structural signal.

    Rules:
    1. Record absorption candle (high volume + small range)
    2. Check next 1-2 candles for displacement beyond absorption candle's high/low
    3. If displacement confirmed → absorption is valid
    4. If no displacement within 2 candles → it was exhaustion, not absorption
    """

    def __init__(self, displacement_candles: int = 2):
        """
        Args:
            displacement_candles: Number of candles to wait for displacement (default 2).
        """
        self._displacement_candles = displacement_candles
        self._pending_absorptions: list[dict] = []

    def record_absorption(
        self,
        candle: OHLC,
        direction: str,
    ) -> None:
        """Record an absorption candle for displacement validation.

        Args:
            candle: The absorption candle.
            direction: Expected direction ("LONG" or "SHORT").
        """
        self._pending_absorptions.append({
            "time": candle.time,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "direction": direction,
            "candles_waited": 0,
        })

    def validate_displacement(self, current_candle: OHLC) -> list[AbsorptionValidationResult]:
        """Check if any pending absorptions have been confirmed by displacement.

        Args:
            current_candle: Current candle to check against pending absorptions.

        Returns:
            List of validation results for confirmed absorptions.
        """
        results = []
        remaining = []

        for absorption in self._pending_absorptions:
            absorption["candles_waited"] += 1

            # Check for displacement
            displacement = self._check_displacement(current_candle, absorption)

            if displacement:
                # Confirmed! Price displaced beyond absorption candle
                results.append(AbsorptionValidationResult(
                    valid=True,
                    direction=absorption["direction"],
                    displacement_confirmed=True,
                    reason=f"Absorption confirmed by {absorption['direction']} displacement beyond {absorption['direction'].lower()} candle",
                ))
                logger.info(
                    "Absorption confirmed: %s displacement beyond %s candle at %s",
                    absorption["direction"],
                    "high" if absorption["direction"] == "LONG" else "low",
                    absorption["time"],
                )
            elif absorption["candles_waited"] < self._displacement_candles:
                # Still waiting for displacement
                remaining.append(absorption)
            else:
                # Timeout — no displacement, it was exhaustion
                results.append(AbsorptionValidationResult(
                    valid=False,
                    direction="",
                    displacement_confirmed=False,
                    reason=f"Absorption rejected: no displacement within {self._displacement_candles} candles (exhaustion, not absorption)",
                ))
                logger.info(
                    "Absorption rejected: no displacement for %s absorption at %s (exhaustion)",
                    absorption["direction"],
                    absorption["time"],
                )

        self._pending_absorptions = remaining
        return results

    def _check_displacement(self, current_candle: OHLC, absorption: dict) -> bool:
        """Check if current candle shows displacement beyond absorption candle."""
        direction = absorption["direction"]

        if direction == "LONG":
            # For LONG absorption: need displacement above absorption candle's high
            return current_candle.high > absorption["high"]
        elif direction == "SHORT":
            # For SHORT absorption: need displacement below absorption candle's low
            return current_candle.low < absorption["low"]

        return False

    def reset(self) -> None:
        """Reset absorption validator for new session."""
        self._pending_absorptions.clear()