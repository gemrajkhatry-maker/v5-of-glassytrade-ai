"""Probability inference port — abstract interface for ML probability models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IProbabilityInference(ABC):
    """Abstraction for probability inference (LGBM, etc.).

    Domain defines this port. Infrastructure provides the adapter.
    """

    @abstractmethod
    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Run probability inference on features.

        Returns dict with keys like: direction, confidence, probability, etc.
        """
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if model is loaded and ready."""
        ...
