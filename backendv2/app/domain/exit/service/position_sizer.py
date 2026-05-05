"""Position sizing — deterministic fixed-fractional calculator."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


RISK_PER_TRADE_PCT = 0.005
ABSOLUTE_CEILING_PCT = 0.01


@dataclass(frozen=True)
class PositionSize:
    """Result of position sizing calculation."""

    lots: int
    risk_amount: float
    risk_pct: float
    valid: bool
    reason: str


class PositionSizer:
    """Fixed fractional sizing (risk budget × point value)."""

    @staticmethod
    def calculate(
        equity: float,
        entry_price: float,
        stop_loss: float,
        point_value: float,
        risk_pct: float = RISK_PER_TRADE_PCT,
    ) -> PositionSize:
        if equity <= 0:
            return PositionSize(0, 0.0, 0.0, False, "Equity is zero or negative")

        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return PositionSize(0, 0.0, 0.0, False, "Stop loss equals entry")

        if point_value <= 0:
            return PositionSize(0, 0.0, 0.0, False, "Point value is zero or negative")

        risk_amount = equity * risk_pct
        risk_per_lot = risk_per_unit * point_value
        if risk_per_lot <= 0:
            return PositionSize(0, 0.0, 0.0, False, "Risk per lot is zero")

        lots = int(risk_amount / risk_per_lot)
        max_risk = equity * ABSOLUTE_CEILING_PCT
        actual_risk = lots * risk_per_lot

        if actual_risk > max_risk:
            lots = int(max_risk / risk_per_lot)
            actual_risk = lots * risk_per_lot

        actual_risk_pct = actual_risk / equity if equity > 0 else 0.0

        if lots <= 0:
            return PositionSize(
                0,
                0.0,
                0.0,
                False,
                f"Insufficient equity for 1 lot (need {risk_per_lot:.0f} risk, have {risk_amount:.0f})",
            )

        logger.debug(
            "Position sizing: equity=%.2f risk=%.2f (%.2f%%) lots=%d",
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
        if lots <= 0 or price_velocity <= 0:
            return lots, ""

        if price_velocity > 0.1:
            adjusted = max(1, int(lots * 0.7))
            reason = f"Velocity {price_velocity:.3f}/s > 0.1 — reduced {lots} → {adjusted} lots (70% scale)"
            logger.info(reason)
            return adjusted, reason

        if price_velocity < 0.02:
            return lots, f"Velocity {price_velocity:.3f}/s < 0.02 — full size ({lots} lots)"

        adjusted = max(1, int(lots * 0.85))
        return adjusted, f"Velocity {price_velocity:.3f}/s moderate — {lots} → {adjusted} lots (85% scale)"
