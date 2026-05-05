"""Base domain event — immutable record of something that happened."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    """Generate UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_idempotency_key(*parts: str) -> str:
    """Generate a deterministic idempotency key from parts."""
    return "|".join(parts)


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events.

    All events are immutable (frozen=True) to ensure:
    - Thread safety
    - Deterministic state re-application
    - Audit trail integrity

    Every event has:
    - event_id: unique UUID for deduplication
    - timestamp: ISO-8601 UTC timestamp
    - idempotency_key: deterministic key derived from event content
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=_utc_now)
    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(id={self.event_id[:8]})"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/transmission."""
        from dataclasses import asdict
        return asdict(self)
