"""Dynamic Spread Normalizer — EMA-based spread normalization per Fabio AMT spec.

Maintains a rolling short-window EMA of the actual tick spread to detect
true volatility expansions vs default wide spreads.

Usage:
    normalizer = SpreadNormalizer(ema_period=10)
    normalizer.update(current_spread)
    if normalizer.is_wide_spread(current_spread):
        # Penalize aggression score
        score -= penalty
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SpreadNormalizationResult:
    """Result of spread normalization."""
    current_spread: float
    ema_spread: float
    spread_ratio: float  # current / EMA
    is_wide: bool
    penalty: float


class SpreadNormalizer:
    """Dynamic spread normalization using EMA.

    Maintains a rolling EMA of tick spreads to detect when the current
    spread is abnormally wide (>1.5x EMA). This prevents the system
    from penalizing normal volatility while catching true spread blowouts.

    Per Fabio: "Normalize the spread against a 10-period EMA to detect
    true volatility expansions vs default wide spreads."
    """

    def __init__(self, ema_period: int = 10, wide_threshold: float = 1.5):
        """
        Args:
            ema_period: EMA period for spread calculation (default 10).
            wide_threshold: Current spread / EMA ratio threshold (default 1.5).
        """
        self._ema_period = ema_period
        self._wide_threshold = wide_threshold
        self._alpha = 2.0 / (ema_period + 1)
        self._ema_spread: float = 0.0
        self._initialized: bool = False

    def update(self, current_spread: float) -> None:
        """Update the EMA with current spread.

        Args:
            current_spread: Current bid-ask spread.
        """
        if current_spread <= 0:
            return

        if not self._initialized:
            self._ema_spread = current_spread
            self._initialized = True
        else:
            self._ema_spread = self._alpha * current_spread + (1 - self._alpha) * self._ema_spread

    def normalize(self, current_spread: float) -> SpreadNormalizationResult:
        """Normalize current spread against EMA.

        Args:
            current_spread: Current bid-ask spread.

        Returns:
            SpreadNormalizationResult with ratio and penalty.
        """
        if not self._initialized or self._ema_spread <= 0:
            return SpreadNormalizationResult(
                current_spread=current_spread,
                ema_spread=current_spread,
                spread_ratio=1.0,
                is_wide=False,
                penalty=0.0,
            )

        spread_ratio = current_spread / self._ema_spread
        is_wide = spread_ratio > self._wide_threshold

        # Penalty: linear scaling above threshold
        if is_wide:
            # penalty = (ratio - threshold) / threshold × 0.5, capped at 0.5
            penalty = min(0.5, (spread_ratio - self._wide_threshold) / self._wide_threshold * 0.5)
        else:
            penalty = 0.0

        return SpreadNormalizationResult(
            current_spread=current_spread,
            ema_spread=self._ema_spread,
            spread_ratio=spread_ratio,
            is_wide=is_wide,
            penalty=penalty,
        )

    def is_wide_spread(self, current_spread: float) -> bool:
        """Check if current spread is >1.5x EMA."""
        return self.normalize(current_spread).is_wide

    def get_penalty(self, current_spread: float) -> float:
        """Get aggression score penalty for current spread."""
        return self.normalize(current_spread).penalty

    def reset(self) -> None:
        """Reset spread normalizer for new session."""
        self._ema_spread = 0.0
        self._initialized = False