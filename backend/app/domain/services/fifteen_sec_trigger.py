"""15-Second Trigger Engine — Stub.

Planned feature: Ultra-fast trigger evaluation for scalp entries,
assessing 15-second candles for momentum confirmation.

Status: Stub — types defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TriggerDirection(str, Enum):
    """Direction of the trigger signal."""
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass
class TriggerResult:
    """Result of a 15-second trigger evaluation."""
    direction: TriggerDirection = TriggerDirection.NONE
    triggered: bool = False
    price: float = 0.0
    volume: float = 0.0
    delta: float = 0.0
    reason: str = ""


class FifteenSecTriggerEngine:
    """Evaluate 15-second candle triggers for scalp entries.

    Stub implementation — returns no triggers until fully implemented.
    """

    def evaluate(
        self,
        price: float = 0.0,
        volume: float = 0.0,
        delta: float = 0.0,
        threshold_volume: float = 0.0,
        **kwargs,
    ) -> TriggerResult:
        """Evaluate the 15-second candle for trigger conditions."""
        return TriggerResult()
