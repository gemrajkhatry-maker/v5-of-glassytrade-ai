"""Shared timezone constants.

All timezone-aware datetime operations should use constants from this module
rather than creating inline `timezone(timedelta(...))` objects.

This ensures consistency across the codebase and makes it trivial to adjust
for different market hours if the system is ever deployed to other regions.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta

IST: timezone = timezone(timedelta(hours=5, minutes=30))
"""Indian Standard Time — used by all NSE/MCX/IST timestamps."""

NSE_SESSION_OPEN = time(9, 15)
NSE_OPENING_END = time(9, 30)
NSE_PRIMARY_END = time(11, 30)
NSE_MIDDAY_END = time(14, 0)
NSE_LAST_ENTRY = time(15, 15)       # last new-entry / force-exit start
NSE_SESSION_CLOSE = time(15, 30)    # real exchange close
MCX_SESSION_OPEN = time(9, 0)
MCX_PRE_OPEN_END = time(9, 15)
MCX_MORNING_END = time(14, 0)
MCX_AFTERNOON_END = time(18, 0)
MCX_EVENING_END = time(23, 0)       # close-protection start
MCX_SESSION_CLOSE = time(23, 30)


def today_ist() -> date:
    """Current calendar date in IST — the exchange's date."""
    return datetime.now(tz=IST).date()


_EPOCH_2000 = 946684800


def epoch_to_iso(time_str: str | float | int | None) -> str:
    """Normalize a timestamp or epoch to an ISO-8601 IST string."""
    text = str(time_str or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).isoformat()
    except (TypeError, ValueError):  # silent-except - non-ISO text falls through to epoch parse then returned as-is
        pass
    try:
        epoch = float(text)
    except (TypeError, ValueError):
        return text
    if epoch < _EPOCH_2000:
        return text
    return datetime.fromtimestamp(epoch, tz=IST).isoformat()

