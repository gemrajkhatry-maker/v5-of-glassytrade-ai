"""Domain events — immutable records of things that happened in the domain."""

from app.domain.shared.event.base import DomainEvent
from app.domain.shared.event.market import TickReceived
from app.domain.shared.event.analysis import AMTAnalyzed, AIAnalysisCompleted
from app.domain.shared.event.signal import SignalGenerated, SignalValidated
from app.domain.shared.event.order import OrderPlaced, OrderCancelled, FillReceived
from app.domain.shared.event.position import (
    PositionChanged,
    PositionOpened,
    PositionClosed,
)
from app.domain.shared.event.risk import RiskCheckFailed, DailyLossLimitReached

__all__ = [
    "DomainEvent",
    "TickReceived",
    "AMTAnalyzed",
    "AIAnalysisCompleted",
    "SignalGenerated",
    "SignalValidated",
    "OrderPlaced",
    "OrderCancelled",
    "FillReceived",
    "PositionChanged",
    "PositionOpened",
    "PositionClosed",
    "RiskCheckFailed",
    "DailyLossLimitReached",
]

# Registry for serialization/deserialization
EVENT_TYPES = {
    "DomainEvent": DomainEvent,
    "TickReceived": TickReceived,
    "AMTAnalyzed": AMTAnalyzed,
    "AIAnalysisCompleted": AIAnalysisCompleted,
    "SignalGenerated": SignalGenerated,
    "SignalValidated": SignalValidated,
    "OrderPlaced": OrderPlaced,
    "OrderCancelled": OrderCancelled,
    "FillReceived": FillReceived,
    "PositionChanged": PositionChanged,
    "PositionOpened": PositionOpened,
    "PositionClosed": PositionClosed,
    "RiskCheckFailed": RiskCheckFailed,
    "DailyLossLimitReached": DailyLossLimitReached,
}
