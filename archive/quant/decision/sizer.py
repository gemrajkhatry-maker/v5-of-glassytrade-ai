"""Position Sizer — Fixed fractional sizing per Fabio AMT spec (FR-10-01).

Formula:
  risk_amount = equity × RISK_PER_TRADE_PCT (0.5%)
  risk_per_lot = |entry - SL| × point_value
  lots = risk_amount / risk_per_lot

Hard ceiling: ABSOLUTE_CEILING_PCT (1.0%) per trade (FR-10-05).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from quant.contracts.constants import RISK_PER_TRADE_PCT, ABSOLUTE_CEILING_PCT

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Result of position sizing calculation."""

    lots: int  # Number of lots (0 if sizing fails)
    risk_amount: float  # Actual risk amount in INR
    risk_pct: float  # Actual risk as % of equity
    valid: bool  # True if sizing passes all checks
    reason: str  # Why valid/invalid


class PositionSizer:
    """Fixed fractional position sizing (FR-10-01)."""

    @staticmethod
    def calculate(
        equity: float,
        entry_price: float,
        stop_loss: float,
        point_value: float,
        risk_pct: float = RISK_PER_TRADE_PCT,
    ) -> PositionSize:
        """Calculate position size based on risk.

        Args:
            equity: Account equity.
            entry_price: Entry price.
            stop_loss: Stop loss price.
            point_value: INR value per price point (lot_size × multiplier).
            risk_pct: Risk per trade as fraction (default 0.5%).

        Returns:
            PositionSize with lots, risk amount, and validity.
        """
        if equity <= 0:
            return PositionSize(0, 0, 0, False, "Equity is zero or negative")

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return PositionSize(0, 0, 0, False, "Stop loss equals entry")

        if point_value <= 0:
            return PositionSize(0, 0, 0, False, "Point value is zero or negative")

        risk_amount = equity * risk_pct
        risk_per_lot = risk_per_unit * point_value

        if risk_per_lot <= 0:
            return PositionSize(0, 0, 0, False, "Risk per lot is zero")

        lots = int(risk_amount / risk_per_lot)

        # Hard ceiling: 1% absolute max per trade (FR-10-05)
        max_risk = equity * ABSOLUTE_CEILING_PCT
        actual_risk = lots * risk_per_lot
        if actual_risk > max_risk:
            lots = int(max_risk / risk_per_lot)
            actual_risk = lots * risk_per_lot

        actual_risk_pct = actual_risk / equity if equity > 0 else 0

        if lots <= 0:
            return PositionSize(
                0,
                0,
                0,
                False,
                f"Insufficient equity for 1 lot (need {risk_per_lot:.0f} risk, have {risk_amount:.0f})",
            )

        logger.debug(
            "Position sizing: equity=%.0f risk=%.0f (%.1f%%) lots=%d",
            equity,
            actual_risk,
            actual_risk_pct * 100,
            lots,
        )

        return PositionSize(
            lots=lots,
            risk_amount=actual_risk,
            risk_pct=actual_risk_pct,
            valid=True,
            reason=f"{lots} lots, risk {actual_risk:.0f} ({actual_risk_pct:.2%})",
        )

    @staticmethod
    def apply_velocity_scaling(lots: int, price_velocity: float) -> tuple[int, str]:
        """Scale position size based on price velocity.

        High velocity (>0.1/s) means price is moving fast — reduce size by 30%
        to avoid whipsaw entries. Low velocity (<0.02/s) means calm — full size.

        Args:
            lots: Calculated lots before velocity adjustment.
            price_velocity: Price velocity in points/second.

        Returns:
            (adjusted_lots, reason) tuple.
        """
        if lots <= 0 or price_velocity <= 0:
            return lots, ""

        if price_velocity > 0.1:
            # High velocity — reduce size by 30%
            adjusted = max(1, int(lots * 0.7))
            reason = f"Velocity {price_velocity:.3f}/s > 0.1 — reduced {lots} → {adjusted} lots (70% scale)"
            logger.info(reason)
            return adjusted, reason
        elif price_velocity < 0.02:
            # Low velocity — full size, no adjustment
            return lots, f"Velocity {price_velocity:.3f}/s < 0.02 — full size ({lots} lots)"
        else:
            # Moderate velocity — slight reduction (85%)
            adjusted = max(1, int(lots * 0.85))
            return adjusted, f"Velocity {price_velocity:.3f}/s moderate — {lots} → {adjusted} lots (85% scale)"
