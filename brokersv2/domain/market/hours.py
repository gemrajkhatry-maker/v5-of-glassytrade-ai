"""
Indian market trading session hours with IST enforcement.

All checks are performed in Asia/Kolkata (IST, UTC+5:30).  A MarketClosedError
is raised when an order is attempted outside the session window — callers that
want AMO behaviour must set order.after_market_order=True and route accordingly.

Holiday calendar is maintained as a static set of dates for the current year
and must be refreshed at the start of each calendar year.  An override file
at ``NSE_HOLIDAY_OVERRIDE_PATH`` (env var, defaults to
``/etc/brokersv2/nse_holidays.txt``) can add extra closure dates at runtime
without a code deploy.

Each line in the override file should be: ``YYYY-MM-DD  # optional comment``
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time
from pathlib import Path
from typing import FrozenSet, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Exchange segment → (session_open, session_close) in IST
# Segments match DhanHQ exchangeSegment wire values.
_SEGMENT_SESSIONS: dict[str, tuple[time, time]] = {
    "NSE_EQ":   (time(9, 15), time(15, 30)),
    "NSE_FNO":  (time(9, 15), time(15, 30)),
    "BSE_EQ":   (time(9, 15), time(15, 30)),
    "BSE_FNO":  (time(9, 15), time(15, 30)),
    "MCX_COMM": (time(9, 0),  time(23, 30)),
    "CDS":      (time(9, 0),  time(17, 0)),
    # Fallback for unmapped segments
    "DEFAULT":  (time(9, 15), time(15, 30)),
}

# Weekday indices where markets are open (Mon=0 … Fri=4)
_TRADING_DAYS = frozenset({0, 1, 2, 3, 4})

# ---------------------------------------------------------------------------
# NSE declared trading holidays — update this set every January.
# Source: https://www.nseindia.com/products-services/equity-market-timings-holidays
# ---------------------------------------------------------------------------
_NSE_HOLIDAYS_2025: FrozenSet[date] = frozenset({
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan Eid)
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti / Ram Navami
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2025, 10, 24),  # Diwali Laxmi Puja (Muhurat trading may apply)
    date(2025, 10, 25),  # Diwali-Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurb Sri Guru Nanak Dev Ji
    date(2025, 12, 25),  # Christmas
})

_NSE_HOLIDAYS_2026: FrozenSet[date] = frozenset({
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 20),   # Holi
    date(2026, 3, 30),   # Id-Ul-Fitr (Ramzan Eid) — tentative
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 9, 15),   # Ganesh Chaturthi — tentative
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 11, 14),  # Diwali Laxmi Puja — tentative
    date(2026, 11, 25),  # Prakash Gurpurb Sri Guru Nanak Dev Ji — tentative
    date(2026, 12, 25),  # Christmas
})

_HOLIDAYS_BY_YEAR: dict[int, FrozenSet[date]] = {
    2025: _NSE_HOLIDAYS_2025,
    2026: _NSE_HOLIDAYS_2026,
}


def _load_holiday_overrides() -> FrozenSet[date]:
    """
    Load extra holiday dates from the override file at runtime.

    The file path is read from ``NSE_HOLIDAY_OVERRIDE_PATH`` env var.
    Missing file is silently ignored.  Malformed lines are logged and skipped.
    """
    path_str = os.environ.get(
        "NSE_HOLIDAY_OVERRIDE_PATH", "/etc/brokersv2/nse_holidays.txt"
    )
    override_path = Path(path_str)
    if not override_path.exists():
        return frozenset()

    overrides: set[date] = set()
    try:
        for raw_line in override_path.read_text().splitlines():
            line = raw_line.split("#")[0].strip()
            if not line:
                continue
            try:
                overrides.add(date.fromisoformat(line))
            except ValueError:
                logger.warning("NSE holiday override: invalid date %r — skipped", line)
    except OSError as exc:
        logger.warning("NSE holiday override file unreadable: %s", exc)
    return frozenset(overrides)


def is_nse_holiday(d: date) -> bool:
    """Return True if ``d`` is an NSE declared trading holiday."""
    base = _HOLIDAYS_BY_YEAR.get(d.year, frozenset())
    overrides = _load_holiday_overrides()
    return d in base or d in overrides


class MarketClosedError(Exception):
    """Raised when an order is attempted outside trading hours."""

    def __init__(
        self,
        segment: str,
        now_ist: datetime,
        open_: Optional[time] = None,
        close_: Optional[time] = None,
        reason: str = "",
    ) -> None:
        self.segment = segment
        self.now_ist = now_ist
        self.open_ = open_
        self.close_ = close_
        if reason:
            detail = reason
        elif open_ and close_:
            detail = (
                f"current IST time is {now_ist.strftime('%H:%M:%S')} "
                f"(session {open_}–{close_})"
            )
        else:
            detail = f"current IST time is {now_ist.strftime('%Y-%m-%d %H:%M:%S')}"
        super().__init__(f"Market closed for {segment}: {detail}")


class MarketHoursGate:
    """
    Hard gate that raises MarketClosedError for orders outside Indian trading hours.

    Usage in order placement::

        gate = MarketHoursGate()
        gate.check("NSE_EQ")   # raises if outside 09:15–15:30 IST on weekdays

    The gate does NOT queue orders as AMO; that is the caller's responsibility.
    Pass ``bypass=True`` in tests or dry-run scenarios to skip the check.
    """

    def __init__(self, bypass: bool = False) -> None:
        self._bypass = bypass

    def check(self, exchange_segment: str, at: Optional[datetime] = None) -> None:
        """
        Validate that ``exchange_segment`` is currently in session.

        Args:
            exchange_segment: DhanHQ exchange segment string (e.g. ``"NSE_EQ"``).
            at: Override the current time (useful in tests).

        Raises:
            MarketClosedError: if outside session window or on a weekend.
        """
        if self._bypass:
            return

        now_ist = (at or datetime.now(IST)).astimezone(IST)
        today = now_ist.date()

        # Reject weekends
        if now_ist.weekday() not in _TRADING_DAYS:
            open_, close_ = _SEGMENT_SESSIONS.get(exchange_segment, _SEGMENT_SESSIONS["DEFAULT"])
            raise MarketClosedError(
                exchange_segment, now_ist, open_, close_,
                reason=f"{today.strftime('%A')} is not a trading day",
            )

        # Reject NSE declared holidays
        if is_nse_holiday(today):
            raise MarketClosedError(
                exchange_segment, now_ist,
                reason=f"{today.isoformat()} is an NSE declared trading holiday",
            )

        open_, close_ = _SEGMENT_SESSIONS.get(exchange_segment, _SEGMENT_SESSIONS["DEFAULT"])
        current_time = now_ist.time().replace(tzinfo=None)

        if not (open_ <= current_time <= close_):
            raise MarketClosedError(exchange_segment, now_ist, open_, close_)

    def is_open(self, exchange_segment: str, at: Optional[datetime] = None) -> bool:
        """Return True if the segment is currently in session (no exception)."""
        try:
            self.check(exchange_segment, at=at)
            return True
        except MarketClosedError:
            return False

    @staticmethod
    def session_for(exchange_segment: str) -> tuple[time, time]:
        """Return the (open, close) session times for a segment."""
        return _SEGMENT_SESSIONS.get(exchange_segment, _SEGMENT_SESSIONS["DEFAULT"])
