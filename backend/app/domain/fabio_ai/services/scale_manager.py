"""Scale-in management (Fabio Rule 4: 40/30/30).

Fabio's scale-in strategy:
- Initial entry: 40% of target size
- Step 2 (confirmation): Add 30% when price confirms direction
- Step 3 (breakout): Add final 30% on breakout

This module manages the scale-in state machine for positions.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import Side

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Position

logger = logging.getLogger(__name__)


class ScaleManager:
    """Manages progressive scale-in for positions.

    This is a stateless class - all scale state is stored on Position objects.
    The manager provides the logic to evaluate scale-in triggers.
    """

    # Scale fractions for each step
    SCALE_STEP_2_FRACTION = 0.30  # Add 30% on confirmation
    SCALE_STEP_3_FRACTION = 0.30  # Add 30% on breakout

    def check_scale_in(
        self,
        position: "Position",
        current_price: float,
    ) -> float:
        """Check if scale-in conditions are met and return fraction to add.

        The scale-in state machine:
        - Step 1: Initial entry, waiting for confirmation price
        - Step 2: Confirmation price hit, add 30%
        - Step 3: Breakout price hit, add final 30%
        - Step >= 3: No more scaling

        Args:
            position: Position to check.
            current_price: Current market price.

        Returns:
            Fraction to add (0.3) or 0.0 if no scale-in triggered.
        """
        if position.scale_step >= 3:
            return 0.0

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry_price = float(position.entry_price)
        initial_stop = float(position.initial_stop)
        risk = abs(entry_price - initial_stop)

        # Don't scale if we're in loss territory
        if risk > 0:
            if is_long and current_price < entry_price:
                return 0.0
            if not is_long and current_price > entry_price:
                return 0.0

        confirm_price = float(position.scale_confirm_price)
        breakout_price = float(position.scale_breakout_price)

        # Step 1 -> Step 2: Confirmation price trigger
        if position.scale_step == 1:
            triggered = (
                (is_long and current_price >= confirm_price > 0)
                or (not is_long and current_price <= confirm_price and confirm_price > 0)
            )
            if triggered:
                position.scale_step = 2
                logger.info(
                    "ScaleManager: SCALE-IN step 2 (confirmation) for %s at %.2f — adding 30%%",
                    position.id, current_price,
                )
                return self.SCALE_STEP_2_FRACTION

        # Step 2 -> Step 3: Breakout price trigger
        if position.scale_step == 2:
            triggered = (
                (is_long and current_price >= breakout_price > 0)
                or (not is_long and current_price <= breakout_price and breakout_price > 0)
            )
            if triggered:
                position.scale_step = 3
                logger.info(
                    "ScaleManager: SCALE-IN step 3 (breakout) for %s at %.2f — adding final 30%%",
                    position.id, current_price,
                )
                return self.SCALE_STEP_3_FRACTION

        return 0.0

    def get_scale_status(self, position: "Position") -> dict:
        """Get current scale-in status for a position.

        Args:
            position: Position to check.

        Returns:
            Dict with scale status information.
        """
        return {
            "scale_step": position.scale_step,
            "scale_confirm_price": float(position.scale_confirm_price),
            "scale_breakout_price": float(position.scale_breakout_price),
            "remaining_fraction": self._get_remaining_fraction(position.scale_step),
        }

    def _get_remaining_fraction(self, scale_step: int) -> float:
        """Get the remaining fraction to be added.

        Args:
            scale_step: Current scale step (1, 2, or 3).

        Returns:
            Remaining fraction (0.6, 0.3, or 0.0).
        """
        if scale_step >= 3:
            return 0.0
        if scale_step == 2:
            return self.SCALE_STEP_3_FRACTION
        return self.SCALE_STEP_2_FRACTION + self.SCALE_STEP_3_FRACTION

    def initialize_scale_prices(
        self,
        position: "Position",
        confirm_price: float,
        breakout_price: float,
    ) -> None:
        """Initialize scale-in price targets on a position.

        This should be called when the position is created if scale-in
        is planned.

        Args:
            position: Position to initialize.
            confirm_price: Price for step 2 confirmation.
            breakout_price: Price for step 3 breakout.
        """
        position.scale_confirm_price = Decimal(str(confirm_price))
        position.scale_breakout_price = Decimal(str(breakout_price))
        position.scale_step = 1  # Ready for first scale-in
        logger.info(
            "ScaleManager: Initialized scale prices for %s — confirm=%.2f, breakout=%.2f",
            position.id, confirm_price, breakout_price,
        )

    def reset_scale_state(self, position: "Position") -> None:
        """Reset scale state (e.g., after a partial exit).

        Args:
            position: Position to reset.
        """
        position.scale_step = 1
        position.scale_confirm_price = Decimal("0")
        position.scale_breakout_price = Decimal("0")
        logger.info("ScaleManager: Reset scale state for %s", position.id)
