"""Aggression Scorer — Multi-signal additive scoring per Fabio AMT spec.

Based on FR-06 (7-component scoring):
1. Footprint 40%+ cells at 3:1 ratio → +1.0
2. CVD slope confirms → +1.0
3. Big trade cluster (3+ prints ≥5x avg) → +1.0
4. Absorption (range < ATR×0.3 AND vol > avg×2) → +0.5
5. OFI aligned (OFI > +0.10 for LONG, < -0.10 for SHORT) → +0.5
6. Confluence (LVN near session level) → +0.5
7. Volume bubble near entry → +0.5

Score thresholds:
- 3.0+ → HIGH confidence
- 2.0+ → MEDIUM confidence (minimum for trade)
- <2.0 → LOW confidence (no trade)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AggressionResult:
    """Result of aggression scoring."""
    score: float = 0.0
    confirmed: bool = False
    pyramid_eligible: bool = False
    confidence: str = "LOW"
    breakdown: dict = field(default_factory=dict)


class AggressionScorer:
    """7-component additive aggression scoring per FR-06.
    
    Supports both legacy sigma-based API and new component-based API.
    """

    def __init__(self, ema_period: int = 20, sigma_threshold: float = 2.5):
        self.ema_period = ema_period
        self.sigma_threshold = sigma_threshold
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0
        self.mean = 0.0
        self.stddev = 0.0
        self._score = 0.0
        self._confirmed = False

    def update(self, value: float) -> dict | None:
        """Update with a value and return sigma-based aggression score.
        
        Legacy API for backward compatibility.
        """
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

    def score(
        self,
        footprint_ratio: float = 0,
        cvd_confirms: bool = False,
        big_trade_cluster: bool = False,
        absorption: bool = False,
        ofi: float = 0,
        lvn_near_level: bool = False,
        volume_bubble: bool = False,
        side: str = "LONG",
    ) -> AggressionResult:
        """
        Calculate aggression score from 7 components (FR-06).
        
        Args:
            footprint_ratio: % of cells at 3:1 ratio or higher
            cvd_confirms: CVD slope confirms direction
            big_trade_cluster: Multiple big trades detected
            absorption: Absorption pattern detected
            ofi: Order Flow Imbalance value
            lvn_near_level: LVN near session level
            volume_bubble: Volume bubble near entry
            side: "LONG" or "SHORT"
        
        Returns:
            AggressionResult with score and confidence
        """
        score = 0.0
        breakdown = {}

        # Component 1: Footprint
        if footprint_ratio >= 0.4:
            score += 1.0
            breakdown["footprint"] = 1.0

        # Component 2: CVD confirmation
        if cvd_confirms:
            score += 1.0
            breakdown["cvd"] = 1.0

        # Component 3: Big trade cluster
        if big_trade_cluster:
            score += 1.0
            breakdown["big_trade"] = 1.0

        # Component 4: Absorption
        if absorption:
            score += 0.5
            breakdown["absorption"] = 0.5

        # Component 5: OFI alignment
        if side == "LONG" and ofi > 0.10:
            score += 0.5
            breakdown["ofi"] = 0.5
        elif side == "SHORT" and ofi < -0.10:
            score += 0.5
            breakdown["ofi"] = 0.5

        # Component 6: LVN confluence
        if lvn_near_level:
            score += 0.5
            breakdown["lvn"] = 0.5

        # Component 7: Volume bubble
        if volume_bubble:
            score += 0.5
            breakdown["bubble"] = 0.5

        # Determine confidence
        if score >= 3.0:
            confidence = "HIGH"
            confirmed = True
            pyramid_eligible = True
        elif score >= 2.0:
            confidence = "MEDIUM"
            confirmed = True
            pyramid_eligible = False
        else:
            confidence = "LOW"
            confirmed = False
            pyramid_eligible = False

        self._score = score
        self._confirmed = confirmed

        return AggressionResult(
            score=score,
            confirmed=confirmed,
            pyramid_eligible=pyramid_eligible,
            confidence=confidence,
            breakdown=breakdown,
        )

    def reset(self) -> None:
        """Reset the scorer."""
        self.count = 0
        self.sum = 0.0
        self.sum_sq = 0.0
        self.mean = 0.0
        self.stddev = 0.0
        self._score = 0.0
        self._confirmed = False


class PersistentAggressionScorer:
    """Aggression scorer with persistence requirement."""

    def __init__(self, persistence_bars: int = 3):
        self.persistence_bars = persistence_bars
        self._histories: list[AggressionResult] = []

    def score(self, **kwargs) -> AggressionResult:
        """Score and track persistence."""
        base_scorer = AggressionScorer()
        result = base_scorer.score(**kwargs)
        self._histories.append(result)

        # Keep only recent history
        if len(self._histories) > self.persistence_bars:
            self._histories.pop(0)

        # Check persistence - score must be >= 2.0 for all bars
        persistent = all(r.score >= 2.0 for r in self._histories[-self.persistence_bars:])
        result.confirmed = persistent and result.confirmed

        return result

    def reset(self) -> None:
        self._histories.clear()


def calculate_aggression_score(values: list[float], sigma_threshold: float = 2.5) -> dict | None:
    """Standalone function for sigma-based aggression calculation."""
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
