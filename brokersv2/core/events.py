"""
Core event definitions for the event-driven architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from .types import OrderId, Symbol, CorrelationId


@dataclass(frozen=True)
class Event:
    """Base event class."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[CorrelationId] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TickEvent(Event):
    """Market tick event."""
    symbol: str = ""
    price: float = 0.0
    volume: int = 0
    bid: Optional[float] = None
    ask: Optional[float] = None
    sequence: Optional[int] = None


@dataclass(frozen=True)
class QuoteEvent(Event):
    """Quote update event."""
    symbol: str = ""
    ltp: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    oi: Optional[int] = None


@dataclass(frozen=True)
class DepthEvent(Event):
    """Market depth event."""
    symbol: str = ""
    side: str = ""
    levels: list = field(default_factory=list)


@dataclass(frozen=True)
class CandleEvent(Event):
    """Candle event."""
    symbol: str = ""
    timeframe: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


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