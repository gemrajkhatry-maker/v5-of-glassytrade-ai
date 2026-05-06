"""15-second trigger engine stub."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TriggerDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass
class TriggerResult:
    direction: TriggerDirection = TriggerDirection.NONE
    triggered: bool = False
    price: float = 0.0
    volume: float = 0.0
    delta: float = 0.0
    reason: str = ""


class FifteenSecTriggerEngine:
    def evaluate(
        self,
        price: float = 0.0,
        volume: float = 0.0,
        delta: float = 0.0,
        threshold_volume: float = 0.0,
        **_: object,
    ) -> TriggerResult:
        return TriggerResult()

