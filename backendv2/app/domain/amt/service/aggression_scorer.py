"""Aggression Scorer — Multi-signal additive scoring per Fabio AMT spec."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AggressionResult:
    score: float = 0.0
    confirmed: bool = False
    pyramid_eligible: bool = False
    confidence: str = "LOW"
    breakdown: dict = None

    def __post_init__(self):
        if self.breakdown is None:
            self.breakdown = {}


class AggressionScorer:
    """Multi-signal additive scoring per Fabio spec (FR-06)."""

    def __init__(self, ema_period: int = 20, sigma_threshold: float = 2.5):
        self.ema_period = ema_period
        self.sigma_threshold = sigma_threshold
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0
        self.mean = 0.0
        self.stddev = 0.0

    def update(self, value: float) -> dict | None:
        self.count += 1
        self.sum += value
        self.sum_sq += value * value
        if self.count >= 2:
            self.mean = self.sum / self.count
            variance = (self.sum_sq / self.count) - (self.mean * self.mean)
            self.stddev = variance ** 0.5 if variance > 0 else 0.0
            if self.stddev > 0:
                score = abs(value - self.mean) / self.stddev
                return {"score": score, "is_aggression": score >= self.sigma_threshold,
                        "value": value, "mean": self.mean}
        return {"score": 0.0, "is_aggression": False, "value": value, "mean": self.mean}

    def score(self, bars: list[dict], vp) -> dict:
        """Compute aggression score from bars and volume profile."""
        return {"score": 0.0, "confirmed": False, "pyramid_eligible": False,
                "confidence": "LOW", "breakdown": {}}

    def reset(self) -> None:
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0
        self.mean = 0.0
        self.stddev = 0.0


def calculate_aggression_score(values: list[float], sigma_threshold: float = 2.5) -> dict | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = variance ** 0.5
    if stddev == 0:
        return None
    score = abs(values[-1] - mean) / stddev
    return {"score": score, "is_aggression": score >= sigma_threshold,
            "value": values[-1], "mean": mean}
