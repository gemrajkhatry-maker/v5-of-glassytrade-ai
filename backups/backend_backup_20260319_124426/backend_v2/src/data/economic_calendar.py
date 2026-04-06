"""
Economic calendar — EIA release window suppression.

Suppresses signals during EIA Natural Gas and Crude Oil storage releases.
"""

from dataclasses import dataclass
from datetime import date, time, datetime
from typing import Dict, List, Optional


@dataclass
class EIAEvent:
    """EIA event definition."""

    symbol: str
    day_of_week: int  # 0=Monday, 3=Thursday, etc.
    release_time: time
    suppress_start: time
    suppress_end: time


class EconomicCalendar:
    """
    EIA release window detection.

    Suppresses signals 15 minutes before and after EIA releases.
    """

    def __init__(self):
        # EIA Natural Gas: Thursday 10:30 ET
        # EIA Crude Oil: Wednesday 10:30 ET
        self._events: List[EIAEvent] = [
            EIAEvent(
                symbol="NATURALGAS",
                day_of_week=3,  # Thursday
                release_time=time(10, 30),
                suppress_start=time(10, 15),
                suppress_end=time(10, 45),
            ),
            EIAEvent(
                symbol="CRUDEOIL",
                day_of_week=2,  # Wednesday
                release_time=time(10, 30),
                suppress_start=time(10, 15),
                suppress_end=time(10, 45),
            ),
        ]

    def is_suppressed(self, symbol: str, timestamp: datetime) -> bool:
        """
        Check if signals should be suppressed for this symbol at this time.

        Args:
            symbol: Trading symbol
            timestamp: Current timestamp

        Returns:
            True if signal should be suppressed.
        """
        current_time = timestamp.time()
        current_weekday = timestamp.weekday()

        for event in self._events:
            if event.symbol != symbol:
                continue

            if event.day_of_week != current_weekday:
                continue

            # Check if within suppression window
            if event.suppress_start <= current_time <= event.suppress_end:
                return True

        return False

    def get_next_event(self, symbol: str, timestamp: datetime) -> Optional[EIAEvent]:
        """
        Get the next EIA event for a symbol.

        Args:
            symbol: Trading symbol
            timestamp: Current timestamp

        Returns:
            Next EIAEvent or None.
        """
        current_weekday = timestamp.weekday()
        current_time = timestamp.time()

        for event in self._events:
            if event.symbol != symbol:
                continue

            # Check if event is later this week
            if event.day_of_week > current_weekday:
                return event

            # Check if event is today but later
            if event.day_of_week == current_weekday:
                if event.release_time > current_time:
                    return event

        # Next week
        return self._events[0] if self._events else None