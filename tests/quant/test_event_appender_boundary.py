from __future__ import annotations

from dataclasses import dataclass

from quant.persistence_boundary import EventAppender, PersistenceHealth


@dataclass(frozen=True)
class Event:
    time: str = "t0"


class FailingStore:
    def append(self, event: Event) -> int:
        raise OSError("disk unavailable")


def test_event_appender_marks_persistence_unhealthy_without_raising() -> None:
    health = PersistenceHealth()
    appender = EventAppender(FailingStore(), health)

    assert appender.append(Event()) is None
    assert health.degraded is True
    assert health.reconciliation_required is True
    assert isinstance(health.failure, OSError)
