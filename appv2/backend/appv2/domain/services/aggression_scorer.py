"""Aggression Scorer — composite signal scoring per Fabio AMT.

Scores aggression from 6 signals:
1. Footprint Confirmed (aggressive prints + strong delta)
2. CVD Confirmed (slope aligned with direction)
3. Big Trade (volume > 2× average)
4. Absorption (large range + large vol + small body)
5. OFI Aligned (order flow imbalance significant)
6. Confluence Bonus (LVN near key level)

Score = weighted sum; confirmed if score >= threshold AND persistence >= 2 bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from appv2.config import constants as C


@dataclass
class AggressionResult:
    score: float  # Raw composite score
    confirmed: bool  # Score >= threshold + persistence met
    persistence: int  # Bars confirmed


class PersistentAggressionScorer:
    """Aggression scorer with persistence tracking."""

    # Weights for each signal component
    WEIGHTS = {
        "footprint": 0.25,
        "cvd": 0.25,
        "big_trade": 0.15,
        "absorption": 0.15,
        "ofi": 0.10,
        "confluence": 0.05,
        "volume_bubble": 0.05,
    }

    def __init__(
        self,
        threshold: float = C.AGGRESSION_SIGMA_THRESHOLD,
        persistence_bars: int = C.AGGRESSION_PERSISTENCE_BARS,
    ):
        self._threshold = threshold
        self._persistence_required = persistence_bars
        self._consecutive_confirmed: int = 0
        self._raw_score: float = 0.0

    def score(
        self,
        footprint_confirmed: bool = False,
        cvd_confirmed: bool = False,
        big_trade_confirmed: bool = False,
        absorption_detected: bool = False,
        ofi_aligned: bool = False,
        confluence_bonus: bool = False,
        volume_bubble_near: bool = False,
    ) -> AggressionResult:
        """Compute composite aggression score."""
        self._raw_score = sum(
            self.WEIGHTS[key]
            for key, active in [
                ("footprint", footprint_confirmed),
                ("cvd", cvd_confirmed),
                ("big_trade", big_trade_confirmed),
                ("absorption", absorption_detected),
                ("ofi", ofi_aligned),
                ("confluence", confluence_bonus),
                ("volume_bubble", volume_bubble_near),
            ]
            if active
        )

        # Normalize to sigma-equivalent (0–5 scale)
        normalized = self._raw_score * 5.0

        # Persistence tracking
        is_above_threshold = normalized >= self._threshold
        if is_above_threshold:
            self._consecutive_confirmed += 1
        else:
            self._consecutive_confirmed = 0

        confirmed = self._consecutive_confirmed >= self._persistence_required

        return AggressionResult(
            score=normalized,
            confirmed=confirmed,
            persistence=self._consecutive_confirmed,
        )

    def reset(self) -> None:
        self._consecutive_confirmed = 0
        self._raw_score = 0.0
