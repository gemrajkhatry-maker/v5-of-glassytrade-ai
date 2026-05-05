"""Dynamic R:R Validator — Live Ask price R:R recalculation per Fabio AMT spec.

Recalculates the exact Risk:Reward ratio on the live Level 2 Ask price
right before the market order hits the wire to ensure slippage doesn't ruin the math.

Usage:
    validator = RRValidator(min_rr=1.5)
    result = validator.validate_live_ask(
        entry_ltp=6100.0, stop_loss=6050.0, take_profit=6200.0,
        live_ask=6105.0
    )
    if result.valid:
        # R:R is valid at live Ask price
        return Signal(...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.constants import MIN_RR_RATIO

logger = logging.getLogger(__name__)


@dataclass
class RRValidationResult:
    """Result of live Ask R:R validation."""
    valid: bool
    rr_ratio: float
    live_ask: float
    live_risk: float
    live_reward: float
    reason: str


class RRValidator:
    """Dynamic R:R validator using live Ask price.

    Per Fabio: "Recalculate the exact Risk:Reward ratio on the live Level 2
    Ask price right before the market order hits the wire to ensure slippage
    doesn't ruin the math."

    The system must abort if (Target - LiveAsk) < 1.5 * (LiveAsk - SL).
    """

    def __init__(self, min_rr: float = MIN_RR_RATIO):
        """
        Args:
            min_rr: Minimum R:R ratio (default 1.5 per Fabio spec).
        """
        self._min_rr = min_rr

    def validate_live_ask(
        self,
        entry_ltp: float,
        stop_loss: float,
        take_profit: float,
        live_ask: float,
        is_long: bool = True,
    ) -> RRValidationResult:
        """Validate R:R using live Ask price.

        Args:
            entry_ltp: Original LTP-based entry price.
            stop_loss: Stop loss price.
            take_profit: Take profit price.
            live_ask: Current live Ask price from L2.
            is_long: True for LONG, False for SHORT.

        Returns:
            RRValidationResult with live R:R and validity.
        """
        if live_ask <= 0 or stop_loss <= 0 or take_profit <= 0:
            return RRValidationResult(
                valid=False,
                rr_ratio=0.0,
                live_ask=live_ask,
                live_risk=0.0,
                live_reward=0.0,
                reason="Invalid prices",
            )

        if is_long:
            live_risk = live_ask - stop_loss
            live_reward = take_profit - live_ask
        else:
            live_risk = stop_loss - live_ask
            live_reward = live_ask - take_profit

        if live_risk <= 0:
            return RRValidationResult(
                valid=False,
                rr_ratio=0.0,
                live_ask=live_ask,
                live_risk=live_risk,
                live_reward=live_reward,
                reason="Live Ask beyond stop loss",
            )

        rr_ratio = live_reward / live_risk if live_risk > 0 else 0.0
        valid = rr_ratio >= self._min_rr

        if valid:
            reason = f"Live R:R {rr_ratio:.2f} >= {self._min_rr} at Ask {live_ask:.2f}"
        else:
            reason = f"Live R:R {rr_ratio:.2f} < {self._min_rr} at Ask {live_ask:.2f} — abort"

        return RRValidationResult(
            valid=valid,
            rr_ratio=rr_ratio,
            live_ask=live_ask,
            live_risk=live_risk,
            live_reward=live_reward,
            reason=reason,
        )