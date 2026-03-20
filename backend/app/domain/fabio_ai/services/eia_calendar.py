"""EIA Calendar — Energy Information Administration release window detection (FR-01-07).

Detects EIA release windows for MCX energy commodities:
- NATURALGAS: Thursday 10:30 AM ET = 21:00 IST
- CRUDEOIL: Wednesday 10:30 AM ET = 21:00 IST

Suppresses signals 15 minutes before and after release.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_ET = timezone(timedelta(hours=-5))  # Eastern Time (EST)


@dataclass
class EIAWindow:
    """EIA release window configuration."""

    symbol: str  # NATURALGAS, CRUDEOIL
    release_day: int  # 0=Monday, ..., 6=Sunday
    release_time_et: time  # 10:30 AM ET
    suppression_minutes: int = 15  # Minutes before/after to suppress


# EIA release schedule (ET = Eastern Time)
# NATURALGAS: Thursday 10:30 AM ET
# CRUDEOIL: Wednesday 10:30 AM ET
EIA_SCHEDULE: dict[str, EIAWindow] = {
    "NATURALGAS": EIAWindow(
        symbol="NATURALGAS",
        release_day=3,  # Thursday (0=Mon, 3=Thu)
        release_time_et=time(10, 30),
        suppression_minutes=15,
    ),
    "CRUDEOIL": EIAWindow(
        symbol="CRUDEOIL",
        release_day=2,  # Wednesday (0=Mon, 2=Wed)
        release_time_et=time(10, 30),
        suppression_minutes=15,
    ),
}


class EIACalendar:
    """Detects EIA release windows for MCX energy commodities.

    Usage:
        calendar = EIACalendar()
        if calendar.is_suppressed("NATURALGAS", current_time):
            # Suppress signals for NATURALGAS
    """

    def __init__(self, suppression_minutes: int = 15) -> None:
        self._suppression_minutes = suppression_minutes

    def is_suppressed(self, symbol: str, now: datetime | None = None) -> bool:
        """Check if current time is within EIA release window for symbol.

        Args:
            symbol: Trading symbol (e.g., "NATURALGAS", "CRUDEOIL")
            now: Current time (defaults to now in IST)

        Returns:
            True if within suppression window, False otherwise.
        """
        if symbol not in EIA_SCHEDULE:
            return False

        window = EIA_SCHEDULE[symbol]
        if now is None:
            now = datetime.now(_IST)

        # Convert current time to ET
        now_et = now.astimezone(_ET)

        # Check if today is the release day
        if now_et.weekday() != window.release_day:
            return False

        # Calculate release time in ET for today
        release_dt_et = datetime.combine(
            now_et.date(), window.release_time_et, tzinfo=_ET
        )

        # Calculate suppression window
        suppression_start = release_dt_et - timedelta(minutes=window.suppression_minutes)
        suppression_end = release_dt_et + timedelta(minutes=window.suppression_minutes)

        # Check if current time is within suppression window
        is_suppressed = suppression_start <= now_et <= suppression_end

        if is_suppressed:
            logger.info(
                "EIA SUPPRESSED: %s — within %d min window around %s ET (%s-%s ET)",
                symbol,
                window.suppression_minutes,
                window.release_time_et.strftime("%H:%M"),
                suppression_start.strftime("%H:%M"),
                suppression_end.strftime("%H:%M"),
            )

        return is_suppressed

    def get_next_release(self, symbol: str, now: datetime | None = None) -> datetime | None:
        """Get next EIA release time for symbol (in IST).

        Args:
            symbol: Trading symbol
            now: Current time (defaults to now in IST)

        Returns:
            Next release datetime in IST, or None if symbol not in schedule.
        """
        if symbol not in EIA_SCHEDULE:
            return None

        window = EIA_SCHEDULE[symbol]
        if now is None:
            now = datetime.now(_IST)

        now_et = now.astimezone(_ET)

        # Find next release day
        days_ahead = window.release_day - now_et.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0:
            # Today is release day — check if release time has passed
            release_dt_et = datetime.combine(
                now_et.date(), window.release_time_et, tzinfo=_ET
            )
            if now_et > release_dt_et:
                days_ahead = 7

        next_release_date = now_et.date() + timedelta(days=days_ahead)
        next_release_et = datetime.combine(
            next_release_date, window.release_time_et, tzinfo=_ET
        )

        return next_release_et.astimezone(_IST)

    def get_suppression_window(
        self, symbol: str, now: datetime | None = None
    ) -> tuple[datetime, datetime] | None:
        """Get current suppression window for symbol (in IST).

        Returns:
            (start, end) tuple in IST, or None if not in window.
        """
        if symbol not in EIA_SCHEDULE:
            return None

        window = EIA_SCHEDULE[symbol]
        if now is None:
            now = datetime.now(_IST)

        now_et = now.astimezone(_ET)

        if now_et.weekday() != window.release_day:
            return None

        release_dt_et = datetime.combine(
            now_et.date(), window.release_time_et, tzinfo=_ET
        )
        suppression_start = release_dt_et - timedelta(minutes=window.suppression_minutes)
        suppression_end = release_dt_et + timedelta(minutes=window.suppression_minutes)

        if suppression_start <= now_et <= suppression_end:
            return (
                suppression_start.astimezone(_IST),
                suppression_end.astimezone(_IST),
            )

        return None