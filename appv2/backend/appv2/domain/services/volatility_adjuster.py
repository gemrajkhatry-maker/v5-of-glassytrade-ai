"""Volatility Adjuster — ATR-based position sizing adjustment.

When ATR is high → reduce position size
When ATR is low → normal position size

Adjustment factor = base_atr / current_atr
Clamped to [0.25, 2.0] range
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VolatilityAdjustment:
    current_atr: float
    base_atr: float
    adjustment_factor: float  # Multiplier for position size
    is_high_volatility: bool
    recommended_size_pct: float  # % of normal position size


class VolatilityAdjuster:
    """Adjusts position size based on current market volatility (ATR)."""

    def __init__(
        self,
        base_atr: float = 50.0,  # Baseline ATR for the instrument
        min_factor: float = 0.25,  # Reduce to 25% in extreme volatility
        max_factor: float = 2.0,  # Can double size in very low volatility
        high_vol_threshold: float = 2.0,  # ATR > 2× base = high vol
    ):
        self._base_atr = base_atr
        self._min_factor = min_factor
        self._max_factor = max_factor
        self._high_vol_threshold = high_vol_threshold

    def adjust(
        self,
        current_atr: float,
        normal_position_size: int,
    ) -> VolatilityAdjustment:
        """Compute volatility-adjusted position size.

        Args:
            current_atr: Current ATR value
            normal_position_size: Standard position size in lots

        Returns:
            VolatilityAdjustment with adjusted size factor
        """
        if current_atr <= 0 or self._base_atr <= 0:
            return VolatilityAdjustment(
                current_atr=current_atr,
                base_atr=self._base_atr,
                adjustment_factor=1.0,
                is_high_volatility=False,
                recommended_size_pct=100.0,
            )

        # Adjustment factor = base / current (inverse relationship)
        factor = self._base_atr / current_atr

        # Clamp to range
        factor = max(self._min_factor, min(self._max_factor, factor))

        is_high_vol = current_atr > self._base_atr * self._high_vol_threshold
        recommended_pct = round(factor * 100, 1)

        return VolatilityAdjustment(
            current_atr=round(current_atr, 2),
            base_atr=self._base_atr,
            adjustment_factor=round(factor, 3),
            is_high_volatility=is_high_vol,
            recommended_size_pct=recommended_pct,
        )

    def get_adjusted_size(
        self,
        current_atr: float,
        normal_size: int,
    ) -> int:
        """Get the volatility-adjusted position size in lots."""
        adj = self.adjust(current_atr, normal_size)
        return max(1, int(normal_size * adj.adjustment_factor))

    def update_base_atr(self, new_base_atr: float) -> None:
        """Update the baseline ATR (e.g., from rolling average)."""
        if new_base_atr > 0:
            self._base_atr = new_base_atr
