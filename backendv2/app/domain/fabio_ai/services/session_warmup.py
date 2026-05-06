"""Session warmup filter to avoid opening whipsaw conditions."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.shared.timezones import IST


class SessionWarmupFilter:
    """Blocks all new entry signals during configured warmup interval."""

    def __init__(self, warmup_minutes: int = 15):
        self._warmup_minutes = warmup_minutes
        self._session_open_time: datetime | None = None
        self._warmup_end_time: datetime | None = None

    def set_session_open(self, session_open_time: datetime) -> None:
        self._session_open_time = session_open_time
        self._warmup_end_time = session_open_time + timedelta(minutes=self._warmup_minutes)

    def is_in_warmup(self, current_time: datetime | None = None) -> bool:
        if self._session_open_time is None:
            return False
        now = current_time or datetime.now(IST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)
        return now < self._warmup_end_time

    def warmup_remaining_seconds(self, current_time: datetime | None = None) -> float:
        if self._session_open_time is None:
            return 0.0
        now = current_time or datetime.now(IST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)
        if now >= self._warmup_end_time:
            return 0.0
        return (self._warmup_end_time - now).total_seconds()

    def reset(self) -> None:
        self._session_open_time = None
        self._warmup_end_time = None
