"""Theta Decay Analyzer — calculates theta cost vs expected profit.

Rejects trades where theta cost exceeds threshold % of expected profit.
Theta cost = |theta| × hours_to_expiry

Used for:
- Entry filtering (reject theta-expensive trades)
- Exit timing (accelerating theta = exit signal)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThetaAnalysis:
    theta_per_day: float  # Daily theta decay (negative)
    theta_per_hour: float  # Hourly theta decay
    hours_to_expiry: float
    total_theta_cost: float  # theta × hours remaining
    expected_profit: float
    theta_cost_pct: float  # (total_theta_cost / expected_profit) × 100
    is_viable: bool  # Theta cost < threshold


class ThetaDecayAnalyzer:
    """Analyzes theta cost for option trade viability."""

    def __init__(self, max_theta_cost_pct: float = 20.0):
        self._max_theta_pct = max_theta_cost_pct

    def analyze(
        self,
        theta: float,  # Per day (negative)
        hours_to_expiry: float,
        expected_profit: float,
    ) -> ThetaAnalysis:
        """Analyze theta cost for a potential trade.

        Args:
            theta: Daily theta decay (negative value)
            hours_to_expiry: Hours until option expiry
            expected_profit: Expected profit from trade (absolute)
        """
        theta_per_hour = abs(theta) / 24.0 if theta != 0 else 0.0
        total_cost = theta_per_hour * hours_to_expiry

        theta_pct = 0.0
        if expected_profit > 0:
            theta_pct = (total_cost / expected_profit) * 100

        is_viable = theta_pct < self._max_theta_pct

        return ThetaAnalysis(
            theta_per_day=theta,
            theta_per_hour=theta_per_hour,
            hours_to_expiry=hours_to_expiry,
            total_theta_cost=total_cost,
            expected_profit=expected_profit,
            theta_cost_pct=theta_pct,
            is_viable=is_viable,
        )

    def is_acceptable(
        self,
        theta: float,
        hours_to_expiry: float,
        expected_profit: float,
    ) -> tuple[bool, str]:
        """Quick check for theta viability.

        Returns:
            (acceptable, reason)
        """
        analysis = self.analyze(theta, hours_to_expiry, expected_profit)

        if not analysis.is_viable:
            return False, (
                f"Theta cost {analysis.theta_cost_pct:.0f}% > "
                f"{self._max_theta_pct}% of expected profit"
            )

        if analysis.hours_to_expiry < 1.0:
            return False, "Less than 1 hour to expiry — extreme theta risk"

        return True, ""
