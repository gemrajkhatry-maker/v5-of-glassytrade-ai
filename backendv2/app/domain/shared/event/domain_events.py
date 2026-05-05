"""Domain events for event-driven architecture."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    # All fields in subclasses must have defaults or be keyword-only


@dataclass(frozen=True)
class TickReceived(DomainEvent):
    """A new market tick was received."""
    symbol: str = ""
    price: float = 0.0
    volume: float = 0.0
    timestamp_ms: float = 0.0


@dataclass(frozen=True)  
class AMTAnalyzed(DomainEvent):
    """AMT analysis completed for a symbol."""
    symbol: str = ""
    phase1_result: dict = field(default_factory=dict)
    phase2_result: dict = field(default_factory=dict)
    phase3_result: dict = field(default_factory=dict)
    phase4_result: dict = field(default_factory=dict)
    absorptions_count: int = 0
    vwap: float = 0.0


@dataclass(frozen=True)
class SignalGenerated(DomainEvent):
    """A trading signal was generated."""
    symbol: str = ""
    direction: str = "NO_TRADE"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward: float = 0.0
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class PositionOpened(DomainEvent):
    """A position was opened."""
    position_id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    size: float = 0.0


@dataclass(frozen=True)
class PositionClosed(DomainEvent):
    """A position was closed."""
    position_id: str = ""
    exit_price: float = 0.0
    pnl: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class RiskStateChanged(DomainEvent):
    """Risk state changed (halt/unhalt)."""
    halted: bool = False
    reason: str = ""
    daily_pnl: float = 0.0
    consecutive_losses: int = 0