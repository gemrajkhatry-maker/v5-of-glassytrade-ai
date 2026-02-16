"""Domain events — immutable records of things that happened in the domain.

Each event is a frozen dataclass carrying only the data needed by handlers.
Events flow through the EventBus; services subscribe and react.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.trading.models.value_objects import (
    OHLC, OrderBook, AMTResult,
    ModelWeights, AIAnalysisResult, FactorBreakdown,
)
from app.domain.trading.models.entities import Signal, Position


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DomainEvent:
    """Marker base class for all domain events."""
    pass


# ---------------------------------------------------------------------------
# Market Data Events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TickReceived(DomainEvent):
    """A new market tick arrived for a symbol."""
    symbol: str
    tick: OHLC
    order_book: OrderBook | None = None
    data: tuple[OHLC, ...] = ()  # full history window


# ---------------------------------------------------------------------------
# Analysis Events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnalysisCompleted(DomainEvent):
    """AMT analysis finished for a symbol."""
    symbol: str
    result: AMTResult = field(default_factory=lambda: AMTResult(
        market_state="BALANCED", poc=0, value_area_high=0, value_area_low=0,
    ))


@dataclass(frozen=True)
class PredictionCompleted(DomainEvent):
    """AI prediction engine finished for a symbol."""
    symbol: str
    analysis: AIAnalysisResult | None = None
    predictions: tuple[OHLC, ...] = ()
    weights: ModelWeights = field(default_factory=ModelWeights)
    generation: int = 0


@dataclass(frozen=True)
class AIAnalysisCompleted(DomainEvent):
    """Generative AI analysis finished for a symbol."""
    symbol: str
    direction: str  # "LONG", "SHORT", "FLAT"
    rationale: str
    confidence: str = "High"


# ---------------------------------------------------------------------------
# Trading Events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalGenerated(DomainEvent):
    """A trade signal was generated (not yet risk-validated)."""
    symbol: str
    signal: Signal | None = None


@dataclass(frozen=True)
class OrderRequested(DomainEvent):
    """Risk manager approved a signal for execution."""
    symbol: str
    signal: Signal | None = None


@dataclass(frozen=True)
class PositionOpened(DomainEvent):
    """A new position was opened."""
    symbol: str
    position: Position | None = None


@dataclass(frozen=True)
class PositionClosed(DomainEvent):
    """A position was closed (SL, TP, or manual)."""
    symbol: str
    position: Position | None = None


# ---------------------------------------------------------------------------
# Learning Events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WeightsUpdated(DomainEvent):
    """The learning engine updated model weights."""
    symbol: str
    weights: ModelWeights = field(default_factory=ModelWeights)
    generation: int = 0
