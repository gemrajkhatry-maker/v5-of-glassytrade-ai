"""Timezone helpers for application-wide market timing."""

from __future__ import annotations

from datetime import timezone, timedelta


IST = timezone(timedelta(hours=5, minutes=30))


def ist_now():
    from datetime import datetime

    return datetime.now(tz=IST)


__all__ = ["IST", "ist_now"]

