"""NSE Event Calendar — known high-impact Indian market dates.

Following the eia_calendar.py pattern. Blocks trading on:
- Union Budget day (Feb 1)
- RBI monetary policy announcement dates
- Election result days
- Major global events affecting Indian markets

These dates are hard-coded and should be updated annually.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NSEEvent:
    """A high-impact market event."""

    date: str  # "YYYY-MM-DD"
    label: str  # "UNION_BUDGET" | "RBI_POLICY" | "ELECTION_RESULT" | "FOMC"
    severity: str  # "HIGH" | "MEDIUM"


# ---------------------------------------------------------------------------
# Known high-impact dates for 2025-2026
# Update this list annually.
# ---------------------------------------------------------------------------

_NSE_EVENTS: list[NSEEvent] = [
    # Union Budget (Feb 1 annually)
    NSEEvent(date="2025-02-01", label="UNION_BUDGET", severity="HIGH"),
    NSEEvent(date="2026-02-01", label="UNION_BUDGET", severity="HIGH"),

    # RBI Monetary Policy dates (bimonthly — approximate, verify each year)
    NSEEvent(date="2025-02-07", label="RBI_POLICY", severity="HIGH"),
    NSEEvent(date="2025-04-09", label="RBI_POLICY", severity="HIGH"),
    NSEEvent(date="2025-06-06", label="RBI_POLICY", severity="HIGH"),
    NSEEvent(date="2025-08-08", label="RBI_POLICY", severity="HIGH"),
    NSEEvent(date="2025-10-10", label="RBI_POLICY", severity="HIGH"),
    NSEEvent(date="2025-12-05", label="RBI_POLICY", severity="HIGH"),

    # Election results
    NSEEvent(date="2025-06-04", label="ELECTION_RESULT", severity="HIGH"),

    # FOMC dates affecting global flows (high impact on FII flows)
    NSEEvent(date="2025-03-19", label="FOMC", severity="MEDIUM"),
    NSEEvent(date="2025-05-07", label="FOMC", severity="MEDIUM"),
    NSEEvent(date="2025-06-18", label="FOMC", severity="MEDIUM"),
    NSEEvent(date="2025-07-30", label="FOMC", severity="MEDIUM"),
    NSEEvent(date="2025-09-17", label="FOMC", severity="MEDIUM"),
    NSEEvent(date="2025-11-05", label="FOMC", severity="MEDIUM"),
    NSEEvent(date="2025-12-17", label="FOMC", severity="MEDIUM"),
]


def get_events() -> list[NSEEvent]:
    """Return all known NSE high-impact events."""
    return list(_NSE_EVENTS)


def get_event_dates() -> set[str]:
    """Return a set of all event date strings for easy lookup."""
    return {e.date for e in _NSE_EVENTS}


def is_event_day(date_str: str) -> NSEEvent | None:
    """Check if the given date string (YYYY-MM-DD) is a known event day.

    Args:
        date_str: Date in "YYYY-MM-DD" format.

    Returns:
        NSEEvent if this is a known event day, None otherwise.
    """
    for event in _NSE_EVENTS:
        if event.date == date_str:
            return event
    return None


def should_block_trade(date_str: str, severity_threshold: str = "MEDIUM") -> bool:
    """Check if trading should be blocked on this date.

    Args:
        date_str: Date in "YYYY-MM-DD" format.
        severity_threshold: Minimum severity to block ("MEDIUM" or "HIGH").

    Returns:
        True if trading should be blocked.
    """
    event = is_event_day(date_str)
    if event is None:
        return False
    if severity_threshold == "HIGH":
        return event.severity == "HIGH"
    return True  # MEDIUM threshold blocks both MEDIUM and HIGH


def get_next_release(from_date: str | None = None) -> NSEEvent | None:
    """Get the next upcoming event from the given date.

    Args:
        from_date: Reference date in "YYYY-MM-DD" format (default: today).

    Returns:
        Next NSEEvent after from_date, or None if no more events.
    """
    if from_date is None:
        from_date = datetime.now().strftime("%Y-%m-%d")

    upcoming = [e for e in _NSE_EVENTS if e.date > from_date]
    if not upcoming:
        return None
    return min(upcoming, key=lambda e: e.date)
