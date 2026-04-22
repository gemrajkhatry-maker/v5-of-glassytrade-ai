"""CVD (Cumulative Volume Delta) value object.

Encapsulates CVD slope and divergence detection.
Extracted from the flat AMTResult dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CVDMetrics:
    """Cumulative Volume Delta analysis.

    Attributes:
        slope: Rate of change of cumulative volume delta.
        divergence: Type of divergence detected, if any.
        source: Data source — "underlying" or "option".
    """

    slope: float = 0.0
    divergence: str = ""  # "BULLISH_DIV", "BEARISH_DIV", or ""
    source: str = ""

    @property
    def has_divergence(self) -> bool:
        """Whether CVD divergence is detected."""
        return bool(self.divergence)
