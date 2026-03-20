"""Prediction value objects — AI / ML model outputs.

ModelWeights, FactorBreakdown, and AIAnalysisResult are canonical in
app.domain.trading.models.value_objects.  Re-exported here for backward
compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.trading.models.value_objects import (
    OHLC,
    ModelWeights,
    FactorBreakdown,
    AIAnalysisResult,
)

__all__ = [
    "ModelWeights",
    "FactorBreakdown",
    "AIAnalysisResult",
    "PredictionResult",
]


@dataclass(frozen=True)
class PredictionResult:
    """Combined output of the prediction engine."""
    predictions: tuple[OHLC, ...] = ()
    analysis: AIAnalysisResult | None = None
