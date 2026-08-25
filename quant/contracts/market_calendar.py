"""Exchange holiday calendar (IST dates). Unknown days are not holidays.

Keep this list as the NSE/MCX closed-day gate. Weekend (Sat/Sun) is also closed.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE + MCX common holidays 2026 (trading closed). Update annually.
_HOLIDAYS_2026 = frozenset({
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Ram Navami (tentative — verify vs NSE circular)
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr Ambedkar Jayanti
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 8),   # Diwali / Laxmi Puja (Muhurat session ignored — no algo)
    date(2026, 11, 9),   # Diwali Balipratipada
    date(2026, 12, 25),  # Christmas
})


def is_trading_day(when: date | datetime | None = None) -> bool:
    """True on Mon–Fri that is not in the holiday set."""
    if when is None:
        d = datetime.now(IST).date()
    elif isinstance(when, datetime):
        d = when.astimezone(IST).date() if when.tzinfo else when.date()
    else:
        d = when
    if d.weekday() >= 5:
        return False
    return d not in _HOLIDAYS_2026
