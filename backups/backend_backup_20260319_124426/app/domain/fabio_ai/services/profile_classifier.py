"""Profile Classifier — Volume profile shape analysis & POC migration.

Classifies profile shapes (D/P/b) using distribution skewness, and tracks
Point of Control migration over time.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.trading.models.value_objects import VolumeProfileLevel
from app.domain.fabio_ai.services import mlx_compute as mc


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileShape:
    """Classification of a volume profile's distribution shape."""
    shape: str          # "D" (bell/balanced), "P" (top-heavy), "b" (bottom-heavy), "B" (bimodal)
    skewness: float     # Negative = P-shape, Positive = b-shape, ~0 = D-shape
    kurtosis: float     # High = narrow peak, Low = flat


@dataclass(frozen=True)
class POCMigration:
    """Direction of POC movement over recent sessions."""
    direction: str      # "RISING" | "FALLING" | "STABLE"
    slope: float        # Linear-regression slope of POC values
    count: int          # Number of POC samples used
    signal: str = ""    # "POC_RISING_BULLISH" / "POC_FALLING_BEARISH" / "POC_DIVERGENCE" / ""
    poc_vs_price: str = ""  # "ALIGNED" / "DIVERGENT" / ""


# ---------------------------------------------------------------------------
# Profile Classifier
# ---------------------------------------------------------------------------

SKEW_THRESHOLD = 0.4  # |skewness| > this → asymmetric (P or b)


def _count_peaks(volumes: list[float], min_prominence: float = 0.5) -> int:
    """Count significant peaks in the volume histogram (MLX-accelerated)."""
    return mc.count_peaks(volumes, min_prominence)


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

    if sum(volumes) == 0:
        return ProfileShape(shape="D", skewness=0.0, kurtosis=0.0)

    # MLX-accelerated weighted moments
    skewness, kurtosis, std = mc.weighted_moments(prices, volumes)

    # Classification — check bimodal first (two distinct volume peaks)
    if _count_peaks(volumes) >= 2:
        shape = "B"   # Bimodal = double distribution, two value areas
    elif skewness < -SKEW_THRESHOLD:
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

    def update(self, poc: float, current_price: float = 0.0) -> POCMigration:
        """Record a new POC value and return migration assessment."""
        self._poc_history.append(poc)
        if len(self._poc_history) > self._max_history:
            self._poc_history = self._poc_history[-self._max_history:]
        return self.state(current_price)

    def state(self, current_price: float = 0.0) -> POCMigration:
        n = len(self._poc_history)
        if n < 3:
            return POCMigration(direction="STABLE", slope=0.0, count=n)

        slope = mc.linreg_slope(self._poc_history)
        avg_poc = sum(self._poc_history) / n
        rel_slope = slope / avg_poc if avg_poc != 0 else 0.0

        if rel_slope > 0.0001:
            direction = "RISING"
        elif rel_slope < -0.0001:
            direction = "FALLING"
        else:
            direction = "STABLE"

        # POC migration signal with price alignment
        signal = ""
        poc_vs_price = ""
        if current_price > 0 and n >= 3:
            latest_poc = self._poc_history[-1]
            price_above_poc = current_price > latest_poc

            if direction == "RISING" and price_above_poc:
                signal = "POC_RISING_BULLISH"
                poc_vs_price = "ALIGNED"
            elif direction == "FALLING" and not price_above_poc:
                signal = "POC_FALLING_BEARISH"
                poc_vs_price = "ALIGNED"
            elif direction == "RISING" and not price_above_poc:
                signal = "POC_DIVERGENCE"
                poc_vs_price = "DIVERGENT"
            elif direction == "FALLING" and price_above_poc:
                signal = "POC_DIVERGENCE"
                poc_vs_price = "DIVERGENT"

        return POCMigration(direction=direction, slope=slope, count=n, signal=signal, poc_vs_price=poc_vs_price)
