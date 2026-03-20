"""Aggression Scorer — Multi-signal additive scoring per Fabio AMT spec (FR-06).

Scoring system (max 4.5):
  FR-06-01: Footprint imbalance confirmed (≥40% cells at ≥3:1)     → +1.0
  FR-06-02: CVD slope confirms direction OR divergence               → +1.0
  FR-06-03: Big trade cluster (3+ prints ≥ 5× avg within 2 ticks)    → +1.0
  FR-06-04: Absorption detected (range < ATR×0.3 AND vol > avg×2)    → +0.5
  FR-06-05: OFI aligned (>+0.10 LONG, <-0.10 SHORT)                  → +0.5
  FR-06-06: Combined profile confluence (LVN near session level)      → +0.5
  FR-06-07: Volume bubble within 3 ticks of entry zone                → +0.5

Confidence labels:
  HIGH:   score ≥ 3.0 (also pyramid eligible)
  MEDIUM: score ≥ 2.0 (minimum for trade signal)
  LOW:    score < 2.0  (no trade)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.constants import (
    AGGRESSION_FOOTPRINT,
    AGGRESSION_CVD,
    AGGRESSION_BIG_TRADE,
    AGGRESSION_ABSORPTION,
    AGGRESSION_OFI,
    AGGRESSION_CONFLUENCE,
    AGGRESSION_BUBBLE,
    MIN_AGGRESSION_SCORE,
    PYRAMID_AGGRESSION_SCORE,
)

logger = logging.getLogger(__name__)


@dataclass
class AggressionResult:
    """Result of aggression scoring."""

    score: float  # 0.0 to 4.5
    confirmed: bool  # score ≥ MIN_AGGRESSION_SCORE (2.0)
    pyramid_eligible: bool  # score ≥ PYRAMID_AGGRESSION_SCORE (3.0)
    confidence: str  # "HIGH" | "MEDIUM" | "LOW"
    breakdown: dict  # Individual signal contributions

    @property
    def direction_sign(self) -> int:
        """Return +1 for bullish, -1 for bearish based on dominant signals."""
        bullish = sum(
            1
            for v in self.breakdown.values()
            if v > 0 and "bearish" not in str(v).lower()
        )
        return 1 if bullish > len(self.breakdown) / 2 else -1


class AggressionScorer:
    """Multi-signal additive scoring per Fabio spec (FR-06).

    Each component adds to a running total. The scorer does NOT make
    decisions — it computes a score that other modules use for gating.
    """

    @staticmethod
    def score(
        footprint_confirmed: bool = False,
        cvd_confirmed: bool = False,
        big_trade_confirmed: bool = False,
        absorption_detected: bool = False,
        ofi_aligned: bool = False,
        confluence_bonus: bool = False,
        volume_bubble_near: bool = False,
    ) -> AggressionResult:
        """Compute additive aggression score from individual signals.

        Returns AggressionResult with score, confidence, and breakdown.
        """
        total = 0.0
        breakdown = {}

        if footprint_confirmed:
            total += AGGRESSION_FOOTPRINT
            breakdown["footprint"] = AGGRESSION_FOOTPRINT
        else:
            breakdown["footprint"] = 0.0

        if cvd_confirmed:
            total += AGGRESSION_CVD
            breakdown["cvd"] = AGGRESSION_CVD
        else:
            breakdown["cvd"] = 0.0

        if big_trade_confirmed:
            total += AGGRESSION_BIG_TRADE
            breakdown["big_trade"] = AGGRESSION_BIG_TRADE
        else:
            breakdown["big_trade"] = 0.0

        if absorption_detected:
            total += AGGRESSION_ABSORPTION
            breakdown["absorption"] = AGGRESSION_ABSORPTION
        else:
            breakdown["absorption"] = 0.0

        if ofi_aligned:
            total += AGGRESSION_OFI
            breakdown["ofi"] = AGGRESSION_OFI
        else:
            breakdown["ofi"] = 0.0

        if confluence_bonus:
            total += AGGRESSION_CONFLUENCE
            breakdown["confluence"] = AGGRESSION_CONFLUENCE
        else:
            breakdown["confluence"] = 0.0

        if volume_bubble_near:
            total += AGGRESSION_BUBBLE
            breakdown["bubble"] = AGGRESSION_BUBBLE
        else:
            breakdown["bubble"] = 0.0

        # Cap at 4.5 (plan FR-06 max)
        total = min(total, 4.5)

        # Confidence classification
        if total >= PYRAMID_AGGRESSION_SCORE:
            confidence = "HIGH"
        elif total >= MIN_AGGRESSION_SCORE:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return AggressionResult(
            score=total,
            confirmed=total >= MIN_AGGRESSION_SCORE,
            pyramid_eligible=total >= PYRAMID_AGGRESSION_SCORE,
            confidence=confidence,
            breakdown=breakdown,
        )

    @staticmethod
    def summary(result: AggressionResult) -> str:
        """Human-readable summary of aggression scoring."""
        active = [k for k, v in result.breakdown.items() if v > 0]
        return (
            f"Aggression {result.score:.1f}/4.5 ({result.confidence}) "
            f"signals=[{', '.join(active)}]"
        )
