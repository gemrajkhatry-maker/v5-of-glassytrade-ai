"""Profile Classifier — Volume profile shape analysis & POC migration.

Classifies profile shapes (D/P/b) using distribution skewness, and tracks
Point of Control migration over time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.trading.models.value_objects import VolumeProfileLevel


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileShape:
    """Classification of a volume profile's distribution shape."""
    shape: str          # "D" (bell/balanced), "P" (top-heavy), "b" (bottom-heavy)
    skewness: float     # Negative = P-shape, Positive = b-shape, ~0 = D-shape
    kurtosis: float     # High = narrow peak, Low = flat


@dataclass(frozen=True)
class POCMigration:
    """Direction of POC movement over recent sessions."""
    direction: str      # "RISING" | "FALLING" | "STABLE"
    slope: float        # Linear-regression slope of POC values
    count: int          # Number of POC samples used


# ---------------------------------------------------------------------------
# Profile Classifier
# ---------------------------------------------------------------------------

SKEW_THRESHOLD = 0.4  # |skewness| > this → asymmetric (P or b)


def classify_shape(profile: list[VolumeProfileLevel]) -> ProfileShape:
    """Classify a volume profile's shape by its skewness and kurtosis.

    - **D-shape** (Bell curve): balanced market, rotational.
    - **P-shape** (Negative skew, heavy top): short covering / long liquidation.
    - **b-shape** (Positive skew, heavy bottom): selling exhaustion / accumulation.
    """
    if not profile or len(profile) < 3:
        return ProfileShape(shape="D", skewness=0.0, kurtosis=0.0)

    # Treat profile as discrete distribution: price levels weighted by volume
    prices = [lvl.price for lvl in profile]
    volumes = [lvl.volume for lvl in profile]
    total_vol = sum(volumes)

    if total_vol == 0:
        return ProfileShape(shape="D", skewness=0.0, kurtosis=0.0)

    # Weighted mean
    mean = sum(p * v for p, v in zip(prices, volumes)) / total_vol

    # Weighted variance, skewness, kurtosis
    m2 = m3 = m4 = 0.0
    for p, v in zip(prices, volumes):
        w = v / total_vol
        d = p - mean
        m2 += w * d ** 2
        m3 += w * d ** 3
        m4 += w * d ** 4

    std = math.sqrt(m2) if m2 > 0 else 1e-9
    skewness = m3 / (std ** 3) if std > 1e-9 else 0.0
    kurtosis = (m4 / (std ** 4)) - 3.0 if std > 1e-9 else 0.0  # excess kurtosis

    # Classification
    if skewness < -SKEW_THRESHOLD:
        shape = "P"   # Negative skew = volume concentrated at higher prices
    elif skewness > SKEW_THRESHOLD:
        shape = "b"   # Positive skew = volume concentrated at lower prices
    else:
        shape = "D"   # Symmetric = balanced bell curve

    return ProfileShape(shape=shape, skewness=skewness, kurtosis=kurtosis)


# ---------------------------------------------------------------------------
# POC Migration Tracker
# ---------------------------------------------------------------------------

class POCMigrationTracker:
    """Tracks Point of Control movement over multiple profile snapshots."""

    def __init__(self, max_history: int = 20) -> None:
        self._poc_history: list[float] = []
        self._max_history = max_history

    def reset(self) -> None:
        self._poc_history.clear()

    def update(self, poc: float) -> POCMigration:
        """Record a new POC value and return migration assessment."""
        self._poc_history.append(poc)
        if len(self._poc_history) > self._max_history:
            self._poc_history = self._poc_history[-self._max_history:]
        return self.state()

    def state(self) -> POCMigration:
        n = len(self._poc_history)
        if n < 3:
            return POCMigration(direction="STABLE", slope=0.0, count=n)

        # Linear regression slope
        values = self._poc_history
        sum_x = sum_y = sum_xy = sum_xx = 0.0
        for i in range(n):
            sum_x += i
            sum_y += values[i]
            sum_xy += i * values[i]
            sum_xx += i * i

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            return POCMigration(direction="STABLE", slope=0.0, count=n)

        slope = (n * sum_xy - sum_x * sum_y) / denom

        # Normalize slope relative to average POC value
        avg_poc = sum_y / n if n > 0 else 1.0
        rel_slope = slope / avg_poc if avg_poc != 0 else 0.0

        if rel_slope > 0.0001:
            direction = "RISING"
        elif rel_slope < -0.0001:
            direction = "FALLING"
        else:
            direction = "STABLE"

        return POCMigration(direction=direction, slope=slope, count=n)
