"""Pyramid Manager — Structured add-on to winning positions per Fabio AMT spec (FR-09).

Rules:
  Max 2 adds (3 total entries: 1 initial + 2 adds)
  Each add at different LVN from previous entries
  Add sizes: Add 1 = 100%, Add 2 = 50% of base
  Aggression ≥ PYRAMID_AGGRESSION_SCORE (3.0) required
  Position must be in profit
  After each add: move ALL stops to latest entry SL
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.constants import PYRAMID_AGGRESSION_SCORE

logger = logging.getLogger(__name__)


@dataclass
class PyramidSignal:
    """Signal to add to a winning position."""

    size_multiplier: float  # 1.0 = 100% of base, 0.5 = 50% of base
    level: float  # Price level for the add
    unified_sl: float  # New stop loss for all entries


class PyramidManager:
    """Structured add-on to winning positions (FR-09)."""

    MAX_ADDS = 2  # 3 total entries

    def check_pyramid(
        self,
        entry_price: float,
        current_price: float,
        is_long: bool,
        aggression_score: float,
        add_count: int,
        entry_lvns: list[float],
        current_lvn: float,
        current_sl: float,
    ) -> PyramidSignal | None:
        """Check if a pyramid add is valid.

        Args:
            entry_price: Original entry price.
            current_price: Current market price.
            is_long: True for long position.
            aggression_score: Current aggression score.
            add_count: Number of previous adds (0 or 1).
            entry_lvns: LVN levels used for previous entries.
            current_lvn: Nearest LVN to current price.
            current_sl: Current stop loss.

        Returns:
            PyramidSignal if add is valid, None otherwise.
        """
        # Max adds reached
        if add_count >= self.MAX_ADDS:
            return None

        # Must be in profit
        if is_long:
            if current_price <= entry_price:
                return None
        else:
            if current_price >= entry_price:
                return None

        # Must have aggression ≥ 3.0
        if aggression_score < PYRAMID_AGGRESSION_SCORE:
            return None

        # Must be at different LVN from previous entries
        if current_lvn > 0:
            for prev_lvn in entry_lvns:
                if abs(current_lvn - prev_lvn) < current_lvn * 0.003:  # Within 0.3%
                    return None

        # Size: Add 1 = 100%, Add 2 = 50%
        size_multiplier = 1.0 if add_count == 0 else 0.5

        # Unified SL: based on current price and ATR
        # Move stops to protect pyramid add
        if is_long:
            unified_sl = max(current_sl, current_price * 0.995)
        else:
            unified_sl = min(current_sl, current_price * 1.005)

        logger.info(
            "Pyramid add %d: size=%.0f%% at %.2f, unified SL=%.2f",
            add_count + 1,
            size_multiplier * 100,
            current_price,
            unified_sl,
        )

        return PyramidSignal(
            size_multiplier=size_multiplier,
            level=current_price,
            unified_sl=unified_sl,
        )
