"""
Core event definitions for the event-driven architecture.

Market data event types (TickEvent, DepthEvent, QuoteEvent, CandleEvent) are
defined in brokersv2.domain.market.events using msgspec for high-performance
serialisation and re-exported here for backward compatibility.

All other events (order, fill, position, risk, error, connection, heartbeat)
are defined directly in this module using plain frozen dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from .types import OrderId, Symbol, CorrelationId

# Market data events — canonical definitions live in domain/market/events.py.
# Re-exported here so existing importers (`from brokersv2.core.events import TickEvent`)
# continue to work without changes.
from brokersv2.domain.market.events import (  # noqa: F401
    TickEvent,
    DepthEvent,
    QuoteEvent,
    CandleEvent,
)


@dataclass(frozen=True)
class Event:
    """Base event class."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[CorrelationId] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderEvent(Event):
    """Order lifecycle event."""
    order_id: OrderId = ""
    symbol: Symbol = ""
    side: str = ""
    quantity: float = 0.0
    status: str = ""
    reason: Optional[str] = None


@dataclass(frozen=True)
class FillEvent(Event):
    """Fill event."""
    order_id: OrderId = ""
    symbol: Symbol = ""
    price: float = 0.0
    quantity: float = 0.0


@dataclass(frozen=True)
class PositionEvent(Event):
    """Position change event."""
    symbol: Symbol = ""
    side: str = ""
    quantity: float = 0.0
    avg_price: float = 0.0


@dataclass(frozen=True)
class RiskEvent(Event):
    """Risk violation event."""
    violation_type: str = ""
    symbol: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ErrorEvent(Event):
    """Error event."""
    error_type: str = ""
    message: str = ""
    error_code: Optional[str] = None


@dataclass(frozen=True)
class ConnectionEvent(Event):
    """Connection lifecycle event."""
    connection_id: str = ""
    state: str = ""
    reason: Optional[str] = None


@dataclass(frozen=True)
class HeartbeatEvent(Event):
    """Heartbeat event."""
    connection_id: str = ""
    sequence: int = 0