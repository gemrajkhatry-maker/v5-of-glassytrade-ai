"""Domain events for event-driven architecture.

DEPRECATED: Import from app.domain.shared.event instead.
This module re-exports from the canonical location for backward compatibility.
"""
from __future__ import annotations

from app.domain.shared.event import (
    DomainEvent,
    TickReceived,
    AMTAnalyzed,
    SignalGenerated,
    PositionOpened,
    PositionClosed,
)

# RiskStateChanged is defined in risk.py - import it there
from app.domain.shared.event.risk import RiskStateChanged

__all__ = [
    "DomainEvent",
    "TickReceived",
    "AMTAnalyzed",
    "SignalGenerated",
    "PositionOpened",
    "PositionClosed",
    "RiskStateChanged",
]