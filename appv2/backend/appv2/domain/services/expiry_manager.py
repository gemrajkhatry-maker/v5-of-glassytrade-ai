"""Expiry Manager — handles options expiry dates and gamma-trap avoidance.

NSE Weekly Expiry: Every Thursday
MCX Expiry: Varies by contract (last Thursday for monthly)

Gamma-Trap Zone: Expiry day after 14:30 IST — avoid new entries
"""

from __future__ import annotations

from datetime import datetime, date, timedelta
from dataclasses import dataclass
from appv2.domain.services.session_context import IST


@dataclass(frozen=True)
class ExpiryInfo:
    is_expiry_day: bool
    days_to_expiry: float
    is_gamma_trap: bool  # After 14:30 on expiry day
    hours_to_close: float
    next_expiry: str  # ISO date string


class ExpiryManager:
    """Manages options expiry awareness."""

    def __init__(self):
        self._known_expiries: list[date] = self._compute_weekly_expiries(weeks_ahead=8)

    def get_info(self, current_time: datetime | None = None) -> ExpiryInfo:
        """Get current expiry context."""
        now = current_time or datetime.now(IST)
        today = now.date()

        # Check if today is expiry day (Thursday)
        is_expiry = today.weekday() == 3  # Thursday

        # Days to next expiry
        next_expiry = self._get_next_expiry(today)
        days_to_expiry = (next_expiry - today).total_seconds() / 86400

        # Gamma trap: expiry day after 14:30 IST
        is_gamma_trap = False
        if is_expiry:
            t = now.hour * 60 + now.minute
            if t >= 870:  # 14:30 = 14*60 + 30 = 870
                is_gamma_trap = True

        # Hours to market close
        hours_to_close = self._hours_to_close(now)

        return ExpiryInfo(
            is_expiry_day=is_expiry,
            days_to_expiry=days_to_expiry,
            is_gamma_trap=is_gamma_trap,
            hours_to_close=hours_to_close,
            next_expiry=next_expiry.isoformat(),
        )

    def should_allow_entry(self, current_time: datetime | None = None) -> tuple[bool, str]:
        """Check if new entries should be allowed given expiry context.

        Returns:
            (allowed, reason)
        """
        info = self.get_info(current_time)

        if info.is_gamma_trap:
            return False, "Gamma-trap zone — expiry day after 14:30"

        if info.days_to_expiry < 0.25:  # Less than 6 hours
            return False, "Too close to expiry"

        return True, ""

    def _get_next_expiry(self, from_date: date) -> date:
        """Get next Thursday expiry."""
        for expiry in self._known_expiries:
            if expiry >= from_date:
                return expiry
        # Fallback: compute next Thursday
        days_ahead = 3 - from_date.weekday()  # Thursday = 3
        if days_ahead <= 0:
            days_ahead += 7
        return from_date + timedelta(days=days_ahead)

    @staticmethod
    def _compute_weekly_expiries(weeks_ahead: int = 8) -> list[date]:
        """Compute next N weekly expiry dates (Thursdays)."""
        today = date.today()
        expiries = []
        # Find next Thursday
        days_to_thursday = (3 - today.weekday()) % 7
        if days_to_thursday == 0:
            days_to_thursday = 7
        next_thursday = today + timedelta(days=days_to_thursday)

        for i in range(weeks_ahead):
            expiries.append(next_thursday + timedelta(weeks=i))
        return expiries

    @staticmethod
    def _hours_to_close(now: datetime) -> float:
        """Hours to NSE market close (15:30 IST)."""
        from appv2.domain.services.session_context import _to_ist
        ist_now = _to_ist(now)
        close_minutes = 15 * 60 + 30  # 15:30
        current_minutes = ist_now.hour * 60 + ist_now.minute
        remaining = max(0, close_minutes - current_minutes)
        return remaining / 60.0
