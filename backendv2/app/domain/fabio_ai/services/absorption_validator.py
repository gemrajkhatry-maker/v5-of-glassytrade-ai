"""Absorption validator for displacement confirmation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.trading.model.value_objects import OHLC


@dataclass
class AbsorptionValidationResult:
    valid: bool
    direction: str
    displacement_confirmed: bool
    reason: str


class AbsorptionValidator:
    """Forward-looking absorber validation:
    high volume + zero-ish range must be followed by displacement.
    """

    def __init__(self, displacement_candles: int = 2):
        self._displacement_candles = displacement_candles
        self._pending_absorptions: list[dict[str, Any]] = []

    def record_absorption(self, candle: OHLC, direction: str) -> None:
        self._pending_absorptions.append(
            {
                "time": str(candle.time),
                "high": float(candle.high),
                "low": float(candle.low),
                "direction": direction,
                "candles_waited": 0,
            }
        )

    def validate_displacement(self, current_candle: OHLC) -> list[AbsorptionValidationResult]:
        results = []
        remaining = []
        for item in self._pending_absorptions:
            item["candles_waited"] += 1
            hit = self._check_displacement(current_candle, item)
            if hit:
                results.append(
                    AbsorptionValidationResult(
                        valid=True,
                        direction=item["direction"],
                        displacement_confirmed=True,
                        reason=f"Absorption confirmed beyond {item['direction']} candle.",
                    )
                )
            elif item["candles_waited"] < self._displacement_candles:
                remaining.append(item)
            else:
                results.append(
                    AbsorptionValidationResult(
                        valid=False,
                        direction="",
                        displacement_confirmed=False,
                        reason=f"No displacement within {self._displacement_candles} candles.",
                    )
                )
        self._pending_absorptions = remaining
        return results

    def _check_displacement(self, current_candle: OHLC, absorption: dict[str, Any]) -> bool:
        if absorption["direction"] == "LONG":
            return float(current_candle.high) > float(absorption["high"])
        if absorption["direction"] == "SHORT":
            return float(current_candle.low) < float(absorption["low"])
        return False

    def reset(self) -> None:
        self._pending_absorptions.clear()
