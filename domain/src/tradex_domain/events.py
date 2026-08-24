"""Domain event types for the reactive bus.

Typed events that flow through the ReactiveBus as Observable emissions.
All events inherit from ``DomainEvent`` which provides ``timestamp`` and
``correlation_id`` via ``kw_only=True`` (Python 3.10+).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from tradex_domain.execution import Fill, Order, OrderRequest
from tradex_domain.market import Candle
from tradex_domain.value_objects import CorrelationId


def _event_timestamp(event: DomainEvent) -> datetime:
    """Derive an event's timestamp from its payload when the payload carries
    one (Fill/Candle/Quote/Depth), else fall back to wall-clock UTC."""
    for name in ("order", "fill", "candle", "request", "quote", "depth"):
        payload = getattr(event, name, None)
        ts = getattr(payload, "timestamp", None)
        if isinstance(ts, datetime):
            return ts
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Base for all domain events. Subclasses carry specific payloads.

    ``timestamp`` defaults to the payload's market timestamp when the payload
    carries one, so an event's timestamp reflects the market instant that
    produced it rather than the wall-clock instant it was published — making
    event logs reproducible from the same market stream.
    """

    timestamp: datetime | None = field(default=None)
    correlation_id: CorrelationId | None = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", _event_timestamp(self))


@dataclass(frozen=True, slots=True)
class OrderPlaced(DomainEvent):
    order: Order


@dataclass(frozen=True, slots=True)
class OrderFilled(DomainEvent):
    fill: Fill


@dataclass(frozen=True, slots=True)
class OrderRejected(DomainEvent):
    order: Order
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CandleReceived(DomainEvent):
    candle: Candle


@dataclass(frozen=True, slots=True)
class ErrorOccurred(DomainEvent):
    error: Exception


@dataclass(frozen=True, slots=True)
class PlaceOrderCommand(DomainEvent):
    """CQRS command — strategies publish this instead of calling broker directly."""

    request: OrderRequest


__all__ = [
    "CandleReceived",
    "DomainEvent",
    "ErrorOccurred",
    "OrderFilled",
    "OrderPlaced",
    "OrderRejected",
    "PlaceOrderCommand",
]
