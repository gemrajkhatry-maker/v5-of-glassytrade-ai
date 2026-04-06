"""
Aggression scorer — additive weighted scoring (max 4.5, 7 components).

Components:
- Footprint imbalance: +1.0
- CVD confirmation: +1.0
- Big trade cluster: +1.0
- Absorption: +0.5
- OFI aligned: +0.5
- Confluence bonus: +0.5
- Volume bubble: +0.5
"""

from dataclasses import dataclass
from typing import Dict

from src.config.engine_config import CFG


@dataclass
class AggressionResult:
    """Aggression scoring result."""

    score: float
    confirmed: bool
    pyramid_eligible: bool
    confidence: str  # HIGH, MEDIUM, LOW
    breakdown: Dict[str, float]


class AggressionScorer:
    """
    Multi-signal additive scoring per Fabio spec.

    Max score: 4.5
    Min for trade: 2.0
    Min for pyramid: 3.0
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
        """
        Calculate aggression score from 7 components.

        Args:
            footprint_confirmed: ≥40% cells at 3:1 ratio
            cvd_confirmed: CVD slope confirms direction OR divergence
            big_trade_confirmed: 3+ institutional prints within 2 ticks
            absorption_detected: Absorption candle at entry level
            ofi_aligned: OFI > +0.10 for LONG, < -0.10 for SHORT
            confluence_bonus: LVN within ±3 ticks of session level
            volume_bubble_near: Directional bubble within 3 ticks of entry

        Returns:
            AggressionResult with score and metadata.
        """
        breakdown = {}

        # Calculate each component
        if footprint_confirmed:
            breakdown["footprint"] = CFG.aggression_footprint_weight
        else:
            breakdown["footprint"] = 0.0

        if cvd_confirmed:
            breakdown["cvd"] = CFG.aggression_cvd_weight
        else:
            breakdown["cvd"] = 0.0

        if big_trade_confirmed:
            breakdown["big_trade"] = CFG.aggression_big_trade_weight
        else:
            breakdown["big_trade"] = 0.0

        if absorption_detected:
            breakdown["absorption"] = CFG.aggression_absorption_weight
        else:
            breakdown["absorption"] = 0.0

        if ofi_aligned:
            breakdown["ofi"] = CFG.aggression_ofi_weight
        else:
            breakdown["ofi"] = 0.0

        if confluence_bonus:
            breakdown["confluence"] = CFG.aggression_confluence_weight
        else:
            breakdown["confluence"] = 0.0

        if volume_bubble_near:
            breakdown["bubble"] = CFG.aggression_bubble_weight
        else:
            breakdown["bubble"] = 0.0

        # Calculate total score
        total = sum(breakdown.values())

        # Determine confidence level
        if total >= CFG.high_confidence_threshold:
            confidence = "HIGH"
        elif total >= CFG.min_aggression_score:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return AggressionResult(
            score=total,
            confirmed=total >= CFG.min_aggression_score,
            pyramid_eligible=total >= CFG.pyramid_aggression_score,
            confidence=confidence,
            breakdown=breakdown,
        )