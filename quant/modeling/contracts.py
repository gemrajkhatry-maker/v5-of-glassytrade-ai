"""Typed contracts for model evidence and strategy mode transitions."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ForecastStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INFERENCE_FAILED = "INFERENCE_FAILED"


class StrategyMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    TIMESFM_ASSISTED = "TIMESFM_ASSISTED"
    TIMESFM_PRIMARY = "TIMESFM_PRIMARY"
    SAFE_HALT = "SAFE_HALT"


@dataclass(frozen=True)
class ForecastSnapshot:
    symbol: str
    decision_sequence: int
    status: ForecastStatus
    model_version: str | None = None
    failure_reason: str | None = None
    expected_return: float | None = None
    dispersion: float | None = None
    velocity: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.decision_sequence < 0:
            raise ValueError("decision_sequence must be non-negative")
        if self.status is ForecastStatus.AVAILABLE and not self.model_version:
            raise ValueError("model_version is required for AVAILABLE forecast")
        if self.status is not ForecastStatus.AVAILABLE and not self.failure_reason:
            raise ValueError("failure_reason is required for unavailable forecast")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload
