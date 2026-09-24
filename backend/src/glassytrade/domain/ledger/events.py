"""Immutable durable lifecycle event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    aggregate_id: str
    aggregate_sequence: int
    event_type: str
    schema_version: int
    occurred_at: datetime
    received_at: datetime
    correlation_id: str
    causation_id: str | None
    payload: Mapping[str, Any]
    checksum: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "aggregate_id", "event_type", "correlation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.checksum is not None and (
            not isinstance(self.checksum, str) or not self.checksum.strip()
        ):
            raise ValueError("checksum must be a non-empty string or None")
        if not isinstance(self.aggregate_sequence, int) or self.aggregate_sequence <= 0:
            raise ValueError("aggregate_sequence must be positive")
        if not isinstance(self.schema_version, int) or self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for name in ("occurred_at", "received_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.causation_id is not None and not self.causation_id.strip():
            raise ValueError("causation_id must be non-empty or None")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
