"""Port for first-passage probability inference — domain-to-infrastructure boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbabilityEstimate:
    """Output of the first-passage probability model."""
    p_long_target: float       # P(long target hit before stop)
    p_short_target: float      # P(short target hit before stop)
    expected_mfe_long: float   # Predicted median MFE if going long (0 if unavailable)
    expected_mfe_short: float  # Predicted median MFE if going short
    calibrated: bool = False   # Whether online calibration is active


class IProbabilityInference(ABC):
    """Abstraction for first-passage probability inference (LightGBM or similar)."""

    @abstractmethod
    def estimate(self, features: dict[str, float]) -> ProbabilityEstimate:
        """Predict first-passage probabilities from microstructure features."""

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if model is loaded and ready."""


class NoOpProbabilityAdapter(IProbabilityInference):
    """Dummy adapter that returns neutral estimates — used when model is not trained."""

    def estimate(self, features: dict[str, float]) -> ProbabilityEstimate:
        return ProbabilityEstimate(
            p_long_target=0.5,
            p_short_target=0.5,
            expected_mfe_long=0.0,
            expected_mfe_short=0.0,
        )

    def is_ready(self) -> bool:
        return True
