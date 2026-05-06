"""Dynamic spread normalization for AMT execution safety."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpreadNormalizationResult:
    """Result of spread normalization."""

    current_spread: float
    ema_spread: float
    spread_ratio: float
    is_wide: bool
    penalty: float


class SpreadNormalizer:
    """Maintain short-window EMA of tick spread and detect widening."""

    def __init__(self, ema_period: int = 10, wide_threshold: float = 1.5):
        self._ema_period = ema_period
        self._wide_threshold = wide_threshold
        self._alpha = 2.0 / (ema_period + 1)
        self._ema_spread: float = 0.0
        self._initialized: bool = False

    def update(self, current_spread: float) -> None:
        """Update spread EMA.

        Negative / zero spread is ignored because it does not represent
        meaningful liquidity stress.
        """
        spread = float(current_spread)
        if spread <= 0:
            return
        if not self._initialized:
            self._ema_spread = spread
            self._initialized = True
        else:
            self._ema_spread = self._alpha * spread + (1.0 - self._alpha) * self._ema_spread

    def normalize(self, current_spread: float) -> SpreadNormalizationResult:
        """Return normalized spread state."""
        spread = float(current_spread)
        if not self._initialized or self._ema_spread <= 0:
            return SpreadNormalizationResult(
                current_spread=spread,
                ema_spread=spread if spread > 0 else self._ema_spread,
                spread_ratio=1.0,
                is_wide=False,
                penalty=0.0,
            )

        spread_ratio = spread / self._ema_spread
        is_wide = spread_ratio > self._wide_threshold
        if is_wide:
            penalty = min(0.5, (spread_ratio - self._wide_threshold) / self._wide_threshold * 0.5)
        else:
            penalty = 0.0

        return SpreadNormalizationResult(
            current_spread=spread,
            ema_spread=self._ema_spread,
            spread_ratio=spread_ratio,
            is_wide=is_wide,
            penalty=penalty,
        )

    def is_wide_spread(self, current_spread: float) -> bool:
        """Whether spread is wide enough to reduce aggression."""
        return self.normalize(current_spread).is_wide

    def get_penalty(self, current_spread: float) -> float:
        """Return aggression penalty for spread stress."""
        return self.normalize(current_spread).penalty

    def reset(self) -> None:
        """Reset spread state (session boundary)."""
        self._ema_spread = 0.0
        self._initialized = False
