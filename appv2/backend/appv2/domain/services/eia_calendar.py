"""EIA Calendar — economic event suppression window.

Suppresses trading around high-impact economic announcements:
- EIA Crude Oil Inventory (Wednesdays ~10:30 AM ET)
- FOMC Meetings
- NFP (Non-Farm Payroll)
- CPI Releases
- RBI Policy Announcements

For MCX CRUDEOIL, EIA inventory is the most critical event.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class EventImpact(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class EconomicEvent:
    name: str
    date: str  # ISO format
    time_utc: str  # HH:MM
    impact: EventImpact
    currencies: list[str]  # Affected currencies/markets


class EIACalendar:
    """Manages economic event calendar and suppression windows.

    Suppression windows:
    - HIGH impact: 15 min before + 15 min after
    - MEDIUM impact: 5 min before + 10 min after
    - LOW impact: No suppression
    """

    def __init__(self):
        self._events: list[EconomicEvent] = []
        self._suppression_minutes_before: dict[EventImpact, int] = {
            EventImpact.HIGH: 15,
            EventImpact.MEDIUM: 5,
            EventImpact.LOW: 0,
        }
        self._suppression_minutes_after: dict[EventImpact, int] = {
            EventImpact.HIGH: 15,
            EventImpact.MEDIUM: 10,
            EventImpact.LOW: 0,
        }

    def add_event(self, event: EconomicEvent) -> None:
        """Add an economic event to the calendar."""
        self._events.append(event)
        # Keep sorted by date
        self._events.sort(key=lambda e: f"{e.date}T{e.time_utc}")

    def add_weekly_eia(self, day_of_week: int = 2, time_et: str = "10:30") -> None:
        """Add recurring weekly EIA crude oil inventory event.

        Args:
            day_of_week: 2 = Wednesday (default)
            time_et: ET time of release (default: 10:30 AM)
        """
        # Generate events for next 12 weeks
        from datetime import date
        today = date.today()
        # Find next Wednesday
        days_ahead = (day_of_week - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7

        for week in range(12):
            event_date = today + timedelta(days=days_ahead + week * 7)
            self.add_event(EconomicEvent(
                name="EIA Crude Oil Inventory",
                date=event_date.isoformat(),
                time_utc=time_et,
                impact=EventImpact.HIGH,
                currencies=["USD"],
            ))

    def add_fomc(self, dates: list[str]) -> None:
        """Add FOMC meeting dates.

        Args:
            dates: List of ISO date strings for FOMC meeting days
        """
        for d in dates:
            self.add_event(EconomicEvent(
                name="FOMC Rate Decision",
                date=d,
                time_utc="14:00",
                impact=EventImpact.HIGH,
                currencies=["USD"],
            ))

    def add_nfp(self, dates: list[str]) -> None:
        """Add Non-Farm Payroll dates (first Friday of month)."""
        for d in dates:
            self.add_event(EconomicEvent(
                name="Non-Farm Payroll",
                date=d,
                time_utc="08:30",
                impact=EventImpact.HIGH,
                currencies=["USD"],
            ))

    def is_in_suppression_window(
        self,
        current_time: datetime | None = None,
        market: str = "",
    ) -> tuple[bool, EconomicEvent | None]:
        """Check if we're currently in a suppression window.

        Args:
            current_time: Current time (defaults to now UTC)
            market: Filter by market (e.g., "MCX" for EIA events)

        Returns:
            (is_suppressed, event_causing_suppression)
        """
        if current_time is None:
            current_time = datetime.utcnow()

        for event in self._events:
            # Parse event time
            try:
                event_dt = datetime.fromisoformat(f"{event.date}T{event.time_utc}")
            except (ValueError, TypeError):
                continue

            # Convert to minutes from midnight for comparison
            event_minutes = event_dt.hour * 60 + event_dt.minute
            current_minutes = current_time.hour * 60 + current_time.minute

            # Check same date
            if event.date != current_time.strftime("%Y-%m-%d"):
                continue

            before = self._suppression_minutes_before.get(event.impact, 0)
            after = self._suppression_minutes_after.get(event.impact, 0)

            if (event_minutes - before) <= current_minutes <= (event_minutes + after):
                return True, event

        return False, None

    def get_upcoming_events(
        self,
        days_ahead: int = 7,
        impact_filter: EventImpact | None = None,
    ) -> list[EconomicEvent]:
        """Get upcoming economic events."""
        from datetime import date
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        upcoming = []
        for event in self._events:
            try:
                event_date = datetime.fromisoformat(event.date).date()
            except (ValueError, TypeError):
                continue

            if today <= event_date <= end_date:
                if impact_filter is None or event.impact == impact_filter:
                    upcoming.append(event)

        return upcoming

    def get_events_today(self) -> list[EconomicEvent]:
        """Get today's economic events."""
        from datetime import date
        today = date.today().isoformat()
        return [e for e in self._events if e.date == today]

    @property
    def total_events(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        self._events.clear()
