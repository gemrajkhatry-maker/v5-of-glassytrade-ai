"""CVD (Cumulative Volume Delta) value object.

Encapsulates CVD slope and divergence detection.
Extracted from the flat AMTResult dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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


@dataclass
class CVDDataPoint:
    """A single CVD data point."""

    timestamp: str
    cvd_value: float
    price: float
    volume: int = 0


@dataclass
class CVDState:
    """CVD state for a symbol."""

    symbol: str = ""
    current_cvd: float = 0.0
    baseline_cvd: float = 0.0
    trend: str = ""
    divergence: str = ""
    data_points: list[CVDDataPoint] = field(default_factory=list)
    max_data_points: int = 100

    def add_data_point(
        self, timestamp: str, cvd_value: float, price: float, volume: int = 0
    ) -> None:
        """Add a data point to the CVD state."""
        point = CVDDataPoint(
            timestamp=timestamp, cvd_value=cvd_value, price=price, volume=volume
        )
        self.data_points.append(point)
        if len(self.data_points) > self.max_data_points:
            self.data_points = self.data_points[-self.max_data_points :]

    def calculate_slope(self) -> float:
        """Calculate the slope of CVD."""
        if len(self.data_points) < 2:
            return 0.0
        points = sorted(self.data_points, key=lambda p: p.timestamp)
        first = points[0]
        last = points[-1]
        if first.cvd_value == 0:
            return 0.0
        return (last.cvd_value - first.cvd_value) / len(points)

    def reset(self) -> None:
        """Reset the CVD state."""
        self.current_cvd = 0.0
        self.data_points = []

    def detect_divergence(self) -> str:
        """Detect divergence between price and CVD."""
        if len(self.data_points) < 2:
            return "NONE"
        points = sorted(self.data_points, key=lambda p: p.timestamp)
        prices_up = points[-1].price > points[0].price
        cvd_up = points[-1].cvd_value > points[0].cvd_value
        if prices_up != cvd_up:
            return "BEARISH" if prices_up else "BULLISH"
        return "NONE"
