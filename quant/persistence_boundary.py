"""Small persistence boundary for paper-safe event appends.

The boundary owns failure visibility while leaving EventStore semantics unchanged.
"""

from __future__ import annotations

from typing import ClassVar, Protocol

from quant.events import Event


class EventStorePort(Protocol):
    def append(self, event: Event) -> int: ...


class PersistenceHealth:
    """Runtime-local health markers for persistence failures."""

    # Process-wide DEGRADED_BRIDGE_WRITE latch. EventBus handlers hold no
    # PersistenceHealth instance, so bridge write failures (SQLite saw no row
    # for an event-store position — restart would silently drop it) latch
    # these ClassVars instead of the per-engine instance flags.
    bridge_write_degraded: ClassVar[bool] = False
    bridge_write_failure: ClassVar[Exception | None] = None

    def __init__(self) -> None:
        self.degraded = False
        self.reconciliation_required = False
        self.failure: Exception | None = None

    def mark_failure(self, failure: Exception) -> None:
        self.degraded = True
        self.reconciliation_required = True
        self.failure = failure

    @classmethod
    def mark_bridge_write_failure(cls, failure: Exception) -> None:
        cls.bridge_write_degraded = True
        cls.bridge_write_failure = failure


class EventAppender:
    """Append events and expose failure state without changing caller flow."""

    def __init__(self, store: EventStorePort, health: PersistenceHealth) -> None:
        self._store = store
        self.health = health

    def append(self, event: Event) -> int | None:
        try:
            return self._store.append(event)
        except Exception as exc:
            self.health.mark_failure(exc)
            return None
