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

Directional gate (v6.0, review finding P0-5):
  The additive score above counts ACTIVITY, not AGREEMENT — a large negative
  delta sell climax scores exactly like a large positive one. Callers that
  assert a trade direction pass ``direction`` plus the signed inputs they
  already hold (``cvd_slope``, ``ofi``, ``norm_delta``, ``absorption_side``):

  * each signed component scores only when it agrees with the direction;
  * absorbed volume with an unreadable side earns no credit (fail-closed);
  * if the net delta slope OPPOSES the direction the whole score is clamped
    to 0.0 (max 4.5) and ``direction_opposed`` is set.

  Callers that pass no ``direction`` keep the legacy additive behaviour, so
  display/journal paths are unchanged.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

import logging
from dataclasses import dataclass
from typing import Optional

from quant.amt.orderflow.cvd import direction_of_signed
from quant.contracts.constants import (
    AGGRESSION_FOOTPRINT,
    AGGRESSION_CVD,
    AGGRESSION_BIG_TRADE,
    AGGRESSION_ABSORPTION,
    AGGRESSION_OFI,
    AGGRESSION_CONFLUENCE,
    AGGRESSION_BUBBLE,
    MIN_AGGRESSION_SCORE,
    PYRAMID_AGGRESSION_SCORE,
    AGGRESSION_PERSISTENCE_BARS,
)

logger = logging.getLogger(__name__)

_DIRECTIONS = ("LONG", "SHORT")

# Canonical absorption -> trade direction mapping. Passive sellers absorbed
# means a hidden BUYER is present (bullish); passive buyers absorbed means a
# hidden SELLER is present (bearish). This is the single source of truth — the
# same mapping was previously written inline in five places, two of which
# contradicted each other.
_ABSORPTION_DIRECTION = {
    "SELL_ABSORBED": "LONG",
    "BUY_ABSORBED": "SHORT",
}


def canonical_absorption_direction(absorption_side: Optional[str]) -> Optional[str]:
    """Return the trade direction that an absorption reading supports.

    ``None`` when the side is absent or unrecognised (unknown provenance).
    """
    if not absorption_side:
        return None
    return _ABSORPTION_DIRECTION.get(str(absorption_side).strip().upper())


def _is_directional(direction: Optional[str]) -> bool:
    return bool(direction) and str(direction).strip().upper() in _DIRECTIONS


def _opposes_signed(value: Optional[float], direction: str) -> bool:
    """True only when a signed value points the OPPOSITE way to ``direction``."""
    pointed = direction_of_signed(value)
    return pointed is not None and pointed != direction


@dataclass
class AggressionResult:
    """Result of aggression scoring."""

    score: float  # 0.0 to 4.5
    confirmed: bool  # score ≥ MIN_AGGRESSION_SCORE (2.0)
    pyramid_eligible: bool  # score ≥ PYRAMID_AGGRESSION_SCORE (3.0)
    confidence: str  # "HIGH" | "MEDIUM" | "LOW"
    breakdown: dict  # Individual signal contributions
    direction: Optional[str] = None  # asserted trade direction, if any
    direction_opposed: bool = False  # net delta slope opposed -> score clamped


class AggressionScorer:
    """Multi-signal additive scoring per Fabio spec (FR-06).

    Each component adds to a running total. The scorer does NOT make
    decisions — it computes a score that other modules use for gating.

    Configurable via SymbolConfig for per-symbol thresholds.
    """

    def __init__(
        self,
        min_score: float = MIN_AGGRESSION_SCORE,
        pyramid_score: float = PYRAMID_AGGRESSION_SCORE,
    ) -> None:
        self._min_score = min_score
        self._pyramid_score = pyramid_score

    def score(
        self,
        footprint_confirmed: bool = False,
        cvd_confirmed: bool = False,
        big_trade_confirmed: bool = False,
        absorption_detected: bool = False,
        ofi_aligned: bool = False,
        confluence_bonus: bool = False,
        volume_bubble_near: bool = False,
        direction: Optional[str] = None,
        cvd_slope: Optional[float] = None,
        ofi: Optional[float] = None,
        norm_delta: Optional[float] = None,
        absorption_side: Optional[str] = None,
    ) -> AggressionResult:
        """Compute the aggression score from individual signals.

        Without ``direction`` this is the legacy additive FR-06 score. With a
        ``direction`` of LONG/SHORT, signed components must agree with it and an
        opposing net delta slope clamps the result to 0.0.
        """
        asserted = str(direction).strip().upper() if _is_directional(direction) else None
        gated = asserted is not None
        total = 0.0
        breakdown = {}

        # Footprint delta (signed): opposing aggression is not credit.
        if footprint_confirmed and not (gated and _opposes_signed(norm_delta, asserted)):
            total += AGGRESSION_FOOTPRINT
            breakdown["footprint"] = AGGRESSION_FOOTPRINT
        else:
            breakdown["footprint"] = 0.0

        # Net delta slope (signed). Opposing slope both zeroes this component
        # and triggers the hard clamp below.
        slope_opposed = gated and _opposes_signed(cvd_slope, asserted)
        if cvd_confirmed and not slope_opposed:
            total += AGGRESSION_CVD
            breakdown["cvd"] = AGGRESSION_CVD
        else:
            breakdown["cvd"] = 0.0

        if big_trade_confirmed:
            total += AGGRESSION_BIG_TRADE
            breakdown["big_trade"] = AGGRESSION_BIG_TRADE
        else:
            breakdown["big_trade"] = 0.0

        # Absorption (signed via its side). Under an asserted direction an
        # unreadable side is unknown provenance, not evidence — no credit.
        if gated:
            absorption_ok = (
                absorption_detected
                and canonical_absorption_direction(absorption_side) == asserted
            )
        else:
            absorption_ok = absorption_detected
        if absorption_ok:
            total += AGGRESSION_ABSORPTION
            breakdown["absorption"] = AGGRESSION_ABSORPTION
        else:
            breakdown["absorption"] = 0.0

        # Order Flow Imbalance (signed)
        if ofi_aligned and not (gated and _opposes_signed(ofi, asserted)):
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

        # v6.0 hard clamp: flow pointing the other way voids the score entirely,
        # however much activity was counted.
        if slope_opposed:
            total = 0.0

        # Confidence classification (configurable thresholds)
        if total >= self._pyramid_score:
            confidence = "HIGH"
        elif total >= self._min_score:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return AggressionResult(
            score=total,
            confirmed=total >= self._min_score,
            pyramid_eligible=total >= self._pyramid_score,
            confidence=confidence,
            breakdown=breakdown,
            direction=asserted,
            direction_opposed=slope_opposed,
        )

    @staticmethod
    def summary(result: AggressionResult) -> str:
        """Human-readable summary of aggression scoring."""
        active = [k for k, v in result.breakdown.items() if v > 0]
        return (
            f"Aggression {result.score:.1f}/4.5 ({result.confidence}) "
            f"signals=[{', '.join(active)}]"
        )


class PersistentAggressionScorer:
    """Stateful aggression scorer with persistence filter to prevent signal flicker.

    Wraps AggressionScorer.score() and only emits confirmed/pyramid flags
    after the score has remained above the threshold for N consecutive bars.

    Usage:
        scorer = PersistentAggressionScorer()
        result = scorer.score(footprint_confirmed=True, cvd_confirmed=True, ...)
        # result.confirmed is True only if score >= 2.0 for 3 consecutive bars
    """

    def __init__(
        self,
        persistence_bars: int = AGGRESSION_PERSISTENCE_BARS,
        min_score: float = MIN_AGGRESSION_SCORE,
        pyramid_score: float = PYRAMID_AGGRESSION_SCORE,
    ) -> None:
        self._persistence_bars = persistence_bars
        self._default_persistence = persistence_bars
        self._min_score = min_score
        self._pyramid_score = pyramid_score
        self._scorer = AggressionScorer(
            min_score=min_score,
            pyramid_score=pyramid_score,
        )
        self._confirmed_streak: int = 0
        self._pyramid_streak: int = 0
        self._raw_score_history: list[float] = []

    def set_persistence_for_state(self, market_state: str) -> None:
        """Dynamically adjust persistence bars based on market state.

        PROBING/IMBALANCED: 2 bars (10 min — moves are fast)
        BALANCED: 3 bars (15 min — mean reversion needs more confirmation)
        """
        if market_state in ("PROBING", MarketState.IMBALANCED.value):
            self._persistence_bars = 2
        elif market_state == MarketState.BALANCED:
            self._persistence_bars = 3
        else:
            self._persistence_bars = self._default_persistence

    @property
    def current_persistence(self) -> int:
        return self._persistence_bars

    def reset(self) -> None:
        """Reset persistence state (call at session boundary)."""
        self._confirmed_streak = 0
        self._pyramid_streak = 0
        self._raw_score_history.clear()

    def score(
        self,
        footprint_confirmed: bool = False,
        cvd_confirmed: bool = False,
        big_trade_confirmed: bool = False,
        absorption_detected: bool = False,
        ofi_aligned: bool = False,
        confluence_bonus: bool = False,
        volume_bubble_near: bool = False,
        direction: Optional[str] = None,
        cvd_slope: Optional[float] = None,
        ofi: Optional[float] = None,
        norm_delta: Optional[float] = None,
        absorption_side: Optional[str] = None,
    ) -> AggressionResult:
        """Compute aggression score with persistence filter.

        Raw score is computed each bar. Confirmed/pyramid flags require
        the raw score to be above threshold for N consecutive bars. Directional
        inputs are forwarded so an opposing climax can never build a streak.
        """
        raw_result = self._scorer.score(
            footprint_confirmed=footprint_confirmed,
            cvd_confirmed=cvd_confirmed,
            big_trade_confirmed=big_trade_confirmed,
            absorption_detected=absorption_detected,
            ofi_aligned=ofi_aligned,
            confluence_bonus=confluence_bonus,
            volume_bubble_near=volume_bubble_near,
            direction=direction,
            cvd_slope=cvd_slope,
            ofi=ofi,
            norm_delta=norm_delta,
            absorption_side=absorption_side,
        )

        self._raw_score_history.append(raw_result.score)

        # Update persistence streaks (configurable thresholds)
        if raw_result.score >= self._min_score:
            self._confirmed_streak += 1
        else:
            self._confirmed_streak = 0

        if raw_result.score >= self._pyramid_score:
            self._pyramid_streak += 1
        else:
            self._pyramid_streak = 0

        # Apply persistence filter
        confirmed = self._confirmed_streak >= self._persistence_bars
        pyramid_eligible = self._pyramid_streak >= self._persistence_bars

        if confirmed and pyramid_eligible:
            confidence = "HIGH"
        elif confirmed:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return AggressionResult(
            score=raw_result.score,
            confirmed=confirmed,
            pyramid_eligible=pyramid_eligible,
            confidence=confidence,
            breakdown=raw_result.breakdown,
            direction=raw_result.direction,
            direction_opposed=raw_result.direction_opposed,
        )

    @property
    def confirmed_streak(self) -> int:
        return self._confirmed_streak

    @property
    def raw_history(self) -> list[float]:
        return list(self._raw_score_history)
