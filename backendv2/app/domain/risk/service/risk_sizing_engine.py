"""Risk-based position sizing engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionSize:
    """Result of position sizing calculation."""
    lots: int
    risk_amount: float
    risk_pct: float
    valid: bool
    reason: str


class RiskSizingEngine:
    """Fixed fractional position sizing (FR-10-01)."""

    @staticmethod
    def calculate(
        equity: float,
        entry_price: float,
        stop_loss: float,
        point_value: float,
        risk_pct: float = 0.005,
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

        risk_amount = equity * risk_pct
        full_size = risk_amount / risk_per_unit
        actual_risk_pct = risk_amount / equity

        lots = max(1, int(full_size))

        return PositionSize(
            lots=lots,
            risk_amount=risk_amount,
            risk_pct=actual_risk_pct,
            valid=True,
            reason="OK",
        )
