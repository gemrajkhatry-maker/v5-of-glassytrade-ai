"""Session Warmup Filter — 15-minute pre-market warmup per Fabio AMT spec.

Prevents the algorithm from buying/selling into opening bell whipsaws
and spread blowouts. All structural break signals are muted during warmup.

Usage:
    warmup = SessionWarmupFilter(warmup_minutes=15)
    if warmup.is_in_warmup(current_time, session_open_time):
        # Block all signals during warmup
        return Signal(..., action="BLOCKED", reason="WARMUP")
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from app.shared.timezones import IST

logger = logging.getLogger(__name__)



class SessionWarmupFilter:
    """15-minute warmup filter at session open.

    Blocks all entry signals during the warmup period to avoid:
    - Opening bell whipsaws
    - Spread blowouts
    - Opening auction volatility

    Per Fabio: "Don't trade the first 15 minutes. Let the market establish
    its opening range before committing capital."
    """

    def __init__(self, warmup_minutes: int = 15):
        self._warmup_minutes = warmup_minutes
        self._session_open_time: datetime | None = None
        self._warmup_end_time: datetime | None = None

    def set_session_open(self, session_open_time: datetime) -> None:
        """Set the session open time for warmup calculation.

        Args:
            session_open_time: Datetime when the trading session opens.
        """
        self._session_open_time = session_open_time
        self._warmup_end_time = session_open_time + timedelta(minutes=self._warmup_minutes)
        logger.info(
            "Warmup filter: session open=%s, warmup ends=%s (%d minutes)",
            session_open_time.strftime("%H:%M"),
            self._warmup_end_time.strftime("%H:%M"),
            self._warmup_minutes,
        )

    def is_in_warmup(self, current_time: datetime | None = None) -> bool:
        """Check if current time is within the warmup period.

        Args:
            current_time: Current time (defaults to now in IST).

        Returns:
            True if within warmup period, False otherwise.
        """
        if self._session_open_time is None:
            return False  # No session open set — allow trading

        if current_time is None:
            current_time = datetime.now(IST)

        # Ensure timezone-aware comparison
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=IST)

        is_warmup = current_time < self._warmup_end_time

        if is_warmup:
            remaining = (self._warmup_end_time - current_time).total_seconds() / 60
            logger.debug(
                "Warmup active: %.1f minutes remaining (ends at %s)",
                remaining,
                self._warmup_end_time.strftime("%H:%M"),
            )

        return is_warmup

    def warmup_remaining_seconds(self, current_time: datetime | None = None) -> float:
        """Get remaining warmup time in seconds.

        Returns:
            Seconds remaining in warmup, or 0 if warmup is complete.
        """
        if self._session_open_time is None:
            return 0.0

        if current_time is None:
            current_time = datetime.now(IST)

        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=IST)

        if current_time >= self._warmup_end_time:
            return 0.0

        return (self._warmup_end_time - current_time).total_seconds()

    def reset(self) -> None:
        """Reset warmup filter for new session."""
        self._session_open_time = None
        self._warmup_end_time = None