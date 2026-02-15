"""Prediction value objects — AI / ML model outputs.

These are consumed by the prediction engine, learning engine,
and the TradingSessionService.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.trading.models.value_objects import OHLC


@dataclass(frozen=True)
class ModelWeights:
    trend: float = 0.40
    momentum: float = 0.25
    delta: float = 0.15
    order_book: float = 0.15
    volatility: float = 0.05


@dataclass(frozen=True)
class FactorBreakdown:
    trend: float = 0.0
    momentum: float = 0.0
    delta: float = 0.0
    order_book: float = 0.0
    volatility: float = 0.0


@dataclass(frozen=True)
class AIAnalysisResult:
    sentiment: str  # Sentiment enum value
    confidence: float
    long_term_trend: str  # TrendDirection enum value
    volatility_score: float
    quant_score: float
    projected_price: float
    reasoning: tuple[str, ...] = ()
    factor_breakdown: FactorBreakdown = field(default_factory=FactorBreakdown)


@dataclass(frozen=True)
class PredictionResult:
    """Combined output of the prediction engine."""
    predictions: tuple[OHLC, ...] = ()
    analysis: AIAnalysisResult | None = None
