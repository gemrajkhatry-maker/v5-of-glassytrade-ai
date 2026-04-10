"""Gamma Acceleration Alert — warns about expiry week gamma risk.

On expiry day (Thursday), gamma explodes especially in the last 2 hours.
This detector:
1. Tracks days to expiry
2. Warns when gamma is accelerating
3. Blocks new entries after gamma-trap threshold
4. Suggests position adjustments (tighten SL, reduce size)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum


class GammaRiskLevel(str, Enum):
    LOW = "LOW"  # > 3 days to expiry
    MEDIUM = "MEDIUM"  # 2-3 days to expiry
    HIGH = "HIGH"  # Expiry day, before 14:30
    EXTREME = "EXTREME"  # Expiry day, after 14:30 (gamma trap)


@dataclass(frozen=True)
class GammaAlert:
    risk_level: GammaRiskLevel
    days_to_expiry: float
    hours_to_expiry: float
    is_gamma_trap: bool
    recommended_size_pct: float  # % of normal size
    action: str


class GammaAccelerationDetector:
    """Detects gamma acceleration risk for options trading."""

    def __init__(
        self,
        gamma_trap_hour: int = 14,
        gamma_trap_minute: int = 30,
        low_days: int = 3,
        medium_days: int = 2,
    ):
        self._gamma_trap_hour = gamma_trap_hour
        self._gamma_trap_minute = gamma_trap_minute
        self._low_days = low_days
        self._medium_days = medium_days

    def get_alert(
        self,
        expiry_date: date,
        current_time: datetime | None = None,
    ) -> GammaAlert:
        """Get gamma risk alert for current time.

        Args:
            expiry_date: Options expiry date (weekly Thursday)
            current_time: Current time (defaults to now IST)

        Returns:
            GammaAlert with risk level and recommendations
        """
        from appv2.domain.services.session_context import _to_ist

        now = _to_ist(current_time) if current_time else datetime.now()
        today = now.date()

        days_to_expiry = (expiry_date - today).total_seconds() / 86400
        hours_to_expiry = (expiry_date - today).total_seconds() / 3600

        is_expiry_day = today == expiry_date
        is_gamma_trap = False
        risk_level = GammaRiskLevel.LOW
        action = ""
        size_pct = 100.0

        if days_to_expiry > self._low_days:
            risk_level = GammaRiskLevel.LOW
            action = "Normal trading conditions"
            size_pct = 100.0
        elif days_to_expiry > self._medium_days:
            risk_level = GammaRiskLevel.MEDIUM
            action = "Gamma increasing — reduce size by 25%"
            size_pct = 75.0
        elif days_to_expiry > 0:
            risk_level = GammaRiskLevel.HIGH
            action = "High gamma — reduce size by 50%, tighten SL"
            size_pct = 50.0
        else:
            days_to_expiry = 0
            risk_level = GammaRiskLevel.HIGH
            action = "Expiry day — trade with caution"
            size_pct = 25.0

        # Check gamma trap (expiry day after 14:30)
        if is_expiry_day:
            t = now.hour * 60 + now.minute
            trap_time = self._gamma_trap_hour * 60 + self._gamma_trap_minute
            if t >= trap_time:
                is_gamma_trap = True
                risk_level = GammaRiskLevel.EXTREME
                action = "GAMMA TRAP — NO new entries. Exit existing positions."
                size_pct = 0.0

        return GammaAlert(
            risk_level=risk_level,
            days_to_expiry=round(max(0, days_to_expiry), 2),
            hours_to_expiry=round(max(0, hours_to_expiry), 1),
            is_gamma_trap=is_gamma_trap,
            recommended_size_pct=round(size_pct, 1),
            action=action,
        )

    def get_next_expiry(self, from_date: date | None = None) -> date:
        """Get next weekly expiry (Thursday)."""
        if from_date is None:
            from_date = date.today()

        # Find next Thursday
        days_ahead = 3 - from_date.weekday()  # Thursday = 3
        if days_ahead <= 0:
            days_ahead += 7  # Next Thursday
        return from_date + timedelta(days=days_ahead)

    def is_expiry_week(self, check_date: date | None = None) -> bool:
        """Check if we're in expiry week."""
        if check_date is None:
            check_date = date.today()

        next_expiry = self.get_next_expiry(check_date)
        days_to = (next_expiry - check_date).days
        return days_to <= 3  # Within 3 days of expiry
