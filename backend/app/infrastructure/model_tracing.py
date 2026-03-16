"""
Model Tracing System - Track all ML/LLM decisions with full attribution.

This module provides:
- Model inference capture
- Feature importance tracking
- SHAP value logging
- Prediction confidence monitoring
- Model version tracking
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ModelType(str, Enum):
    """Types of models in the system."""

    LLM = "LLM"
    PROBABILITY = "PROBABILITY"
    REINFORCEMENT_LEARNING = "RL"
    ENSEMBLE = "ENSEMBLE"


@dataclass
class ModelInference:
    """Complete record of a model inference."""

    inference_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Model identification
    model_type: ModelType = ModelType.LLM
    model_name: str = ""
    model_version: str = ""
    prompt_version: str = ""

    # Input features
    input_features: dict = field(default_factory=dict)
    feature_count: int = 0

    # Output
    predicted_class: str = ""
    confidence: float = 0.0
    probabilities: dict = field(default_factory=dict)

    # Attribution
    feature_importance: dict = field(default_factory=dict)
    shap_values: dict = field(default_factory=dict)
    reasoning_chain: list[str] = field(default_factory=list)

    # Performance
    latency_ms: float = 0.0
    token_count: int = 0

    # Context
    correlation_id: str = ""
    symbol: str = ""
    market_state: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class FeatureImportance:
    """Feature importance tracking."""

    feature_name: str
    importance_score: float
    direction: str = ""  # positive/negative impact
    percentile: float = 0.0


class ModelTracer:
    """
    Centralized model tracing.

    Captures all model inferences with full attribution,
    enabling downstream analysis and debugging.
    """

    def __init__(self, output_dir: str = "logs/observability"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._inferences: list[ModelInference] = []
        self._current_inference: ModelInference | None = None

    def start_inference(
        self,
        model_type: ModelType,
        model_name: str,
        model_version: str = "",
        prompt_version: str = "",
        correlation_id: str = "",
        symbol: str = "",
    ) -> ModelInference:
        """Start tracking a new inference."""
        inference = ModelInference(
            model_type=model_type,
            model_name=model_name,
            model_version=model_version,
            prompt_version=prompt_version,
            correlation_id=correlation_id,
            symbol=symbol,
            latency_ms=time.time(),
        )
        self._current_inference = inference
        return inference

    def add_input_features(self, features: dict) -> None:
        """Add input features to current inference."""
        if self._current_inference:
            self._current_inference.input_features = features
            self._current_inference.feature_count = len(features)

    def add_output(
        self,
        predicted_class: str,
        confidence: float,
        probabilities: dict | None = None,
    ) -> None:
        """Add model output to current inference."""
        if self._current_inference:
            self._current_inference.predicted_class = predicted_class
            self._current_inference.confidence = confidence
            if probabilities:
                self._current_inference.probabilities = probabilities

    def add_reasoning(self, reasoning: str) -> None:
        """Add reasoning step to current inference."""
        if self._current_inference:
            self._current_inference.reasoning_chain.append(reasoning)

    def add_feature_importance(
        self,
        importance: dict[str, float],
        shap_values: dict[str, float] | None = None,
    ) -> None:
        """Add feature importance to current inference."""
        if self._current_inference:
            self._current_inference.feature_importance = importance
            if shap_values:
                self._current_inference.shap_values = shap_values

    def set_market_context(self, market_state: str) -> None:
        """Set market context for current inference."""
        if self._current_inference:
            self._current_inference.market_state = market_state

    def end_inference(self, save: bool = True) -> ModelInference | None:
        """End tracking current inference and optionally save."""
        if self._current_inference:
            # Calculate latency
            self._current_inference.latency_ms = (
                time.time() - self._current_inference.latency_ms
            ) * 1000

            inference = self._current_inference

            if save:
                self._inferences.append(inference)
                self._save_inference(inference)

            self._current_inference = None
            return inference
        return None

    def _save_inference(self, inference: ModelInference) -> None:
        """Save inference to file."""
        filepath = self.output_dir / "model_inference.log"
        with open(filepath, "a") as f:
            f.write(inference.to_json() + "\n")

    def get_inference(self, inference_id: str) -> ModelInference | None:
        """Get inference by ID."""
        for inf in self._inferences:
            if inf.inference_id == inference_id:
                return inf
        return None

    def get_inferences_by_symbol(self, symbol: str) -> list[ModelInference]:
        """Get all inferences for a symbol."""
        return [inf for inf in self._inferences if inf.symbol == symbol]

    def get_inferences_by_correlation(
        self, correlation_id: str
    ) -> list[ModelInference]:
        """Get all inferences for a correlation ID (trace)."""
        return [inf for inf in self._inferences if inf.correlation_id == correlation_id]

    def get_recent_inferences(self, count: int = 100) -> list[ModelInference]:
        """Get most recent inferences."""
        return self._inferences[-count:]


class FeatureTracker:
    """
    Track feature values over time for drift detection.
    """

    def __init__(self, output_dir: str = "logs/observability"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._feature_history: list[dict] = []
        self._feature_stats: dict[str, list[float]] = {}

    def record_features(
        self,
        features: dict[str, float],
        correlation_id: str = "",
        symbol: str = "",
        timestamp: str | None = None,
    ) -> None:
        """Record feature values."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        record = {
            "timestamp": timestamp,
            "correlation_id": correlation_id,
            "symbol": symbol,
            "features": features,
        }

        self._feature_history.append(record)

        # Update rolling statistics
        for name, value in features.items():
            if name not in self._feature_stats:
                self._feature_stats[name] = []
            self._feature_stats[name].append(value)

            # Keep only last 1000 values
            if len(self._feature_stats[name]) > 1000:
                self._feature_stats[name] = self._feature_stats[name][-1000:]

        # Save to file
        filepath = self.output_dir / "feature_values.log"
        with open(filepath, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def get_feature_stats(self, feature_name: str) -> dict | None:
        """Get statistics for a feature."""
        if feature_name not in self._feature_stats:
            return None

        values = self._feature_stats[feature_name]
        if not values:
            return None

        return {
            "count": len(values),
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "recent_10": values[-10:] if len(values) >= 10 else values,
        }

    def detect_drift(self, feature_name: str, threshold: float = 2.0) -> bool:
        """Detect if feature has drifted significantly."""
        stats = self.get_feature_stats(feature_name)
        if not stats or stats["count"] < 30:
            return False

        # Calculate rolling std
        values = self._feature_stats[feature_name][-30:]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std = variance**0.5

        # Check last value
        last_value = values[-1]
        z_score = abs((last_value - mean) / std) if std > 0 else 0

        return z_score > threshold


# Global instances
_model_tracer = ModelTracer()
_feature_tracker = FeatureTracker()


def get_model_tracer() -> ModelTracer:
    return _model_tracer


def get_feature_tracker() -> FeatureTracker:
    return _feature_tracker
