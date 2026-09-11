"""Broker-neutral Indian exchange session and square-off contracts for paper runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

from quant.contracts.market_calendar import IST


class PaperSession(str, Enum):
    NSE = "NSE"
    MCX = "MCX"


_SESSION_BOUNDS = {
    PaperSession.NSE: (time(9, 15), time(15, 30)),
    PaperSession.MCX: (time(9, 0), time(23, 30)),
}


def is_within_session(timestamp: datetime, session: PaperSession) -> bool:
    """Return whether an IST timestamp is inside the inclusive trading window."""
    if not isinstance(timestamp, datetime):
        raise TypeError("timestamp must be a datetime")
    session = PaperSession(session)
    local = timestamp.astimezone(IST) if timestamp.tzinfo else timestamp.replace(tzinfo=IST)
    start, end = _SESSION_BOUNDS[session]
    return start <= local.time() <= end


@dataclass(frozen=True)
class SquareOffPolicy:
    """Deterministic end-of-session policy for paper positions."""

    session: PaperSession

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", PaperSession(self.session))

    def should_square_off(self, timestamp: datetime) -> bool:
        return self._at_or_after_close(timestamp)

    def _at_or_after_close(self, timestamp: datetime) -> bool:
        local = timestamp.astimezone(IST) if timestamp.tzinfo else timestamp.replace(tzinfo=IST)
        return local.time() >= _SESSION_BOUNDS[self.session][1]


def square_off_reason(policy: SquareOffPolicy, timestamp: datetime) -> str | None:
    return "SESSION_CLOSE" if policy.should_square_off(timestamp) else None
