"""
Position sizer — fixed fractional position sizing.

lots = risk_amount / risk_per_lot
Hard ceiling: 1% per trade absolute maximum.
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG


@dataclass
class PositionSize:
    """Position sizing result."""

    lots: int
    risk_amount: float
    risk_pct: float


class PositionSizer:
    """
    Fixed fractional position sizing per FR-10-01.

    Uses static methods for pure function behavior.
    """

    @staticmethod
    def calculate(
        equity: float,
        entry_price: float,
        stop_loss: float,
        point_value: int,
        risk_pct: float = CFG.risk_per_trade_pct,
    ) -> PositionSize:
        """
        Calculate position size.

        Args:
            equity: Account equity
            entry_price: Entry price
            stop_loss: Stop loss price
            point_value: Point value (INR per price point)
            risk_pct: Risk percentage (default 0.5%)

        Returns:
            PositionSize with lots, risk_amount, risk_pct.
        """
        if equity <= 0 or point_value <= 0:
            return PositionSize(lots=0, risk_amount=0.0, risk_pct=0.0)

        # Calculate risk amount
        risk_amount = equity * risk_pct

        # Calculate risk per lot
        price_distance = abs(entry_price - stop_loss)
        risk_per_lot = price_distance * point_value

        if risk_per_lot <= 0:
            return PositionSize(lots=0, risk_amount=0.0, risk_pct=0.0)

        # Calculate lots
        lots = int(risk_amount / risk_per_lot)

        # Hard ceiling: 1% absolute max per trade
        max_risk = equity * CFG.absolute_ceiling_pct
        if lots * risk_per_lot > max_risk:
            lots = int(max_risk / risk_per_lot)

        # Ensure non-negative
        lots = max(0, lots)

        # Calculate actual risk
        actual_risk = lots * risk_per_lot
        actual_risk_pct = actual_risk / equity if equity > 0 else 0.0

        return PositionSize(
            lots=lots,
            risk_amount=actual_risk,
            risk_pct=actual_risk_pct,
        )