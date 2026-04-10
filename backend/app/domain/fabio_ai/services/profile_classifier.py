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

    shape: (
        str  # "D" (bell/balanced), "P" (top-heavy), "b" (bottom-heavy), "B" (bimodal)
    )
    skewness: float  # Negative = P-shape, Positive = b-shape, ~0 = D-shape
    kurtosis: float  # High = narrow peak, Low = flat


@dataclass(frozen=True)
class POCMigration:
    """Direction of POC movement over recent sessions."""

    direction: str  # "RISING" | "FALLING" | "STABLE"
    slope: float  # Linear-regression slope of POC values
    count: int  # Number of POC samples used
    signal: str = (
        ""  # "POC_RISING_BULLISH" / "POC_FALLING_BEARISH" / "POC_DIVERGENCE" / ""
    )
    poc_vs_price: str = ""  # "ALIGNED" / "DIVERGENT" / ""


# ---------------------------------------------------------------------------
# Profile Classifier
# ---------------------------------------------------------------------------

SKEW_THRESHOLD = 0.4  # |skewness| > this → asymmetric (P or b)


def _count_peaks(volumes: list[float], min_prominence: float = 0.25) -> int:
    """Count significant peaks in the volume histogram (MLX-accelerated)."""
    return mc.count_peaks(volumes, min_prominence)


def classify_shape(profile: list[VolumeProfileLevel]) -> ProfileShape:
    """Classify a volume profile's shape by its skewness and kurtosis.

    - **D-shape** (Bell curve): balanced market, rotational.
    - **P-shape** (Negative skew, heavy top): short covering / long liquidation.
    - **b-shape** (Positive skew, heavy bottom): selling exhaustion / accumulation.
    - **B-shape** (Bimodal, two peaks): distributional transition — has LVN gap.
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
        shape = "B"  # Bimodal = double distribution, two value areas
    elif skewness < -SKEW_THRESHOLD:
        shape = "P"  # Negative skew = volume concentrated at higher prices
    elif skewness > SKEW_THRESHOLD:
        shape = "b"  # Positive skew = volume concentrated at lower prices
    else:
        shape = "D"  # Symmetric = balanced bell curve

    # Secondary bimodal check: if shape is D but there's a significant valley
    # between two volume clusters, it's still bimodal (crash + new balance scenario)
    if shape == "D" and len(volumes) >= 10:
        third = len(volumes) // 3
        if third > 0:
            mid_section = volumes[third:2 * third]
            mid_min = min(mid_section) if mid_section else 0
            outer_total = sum(volumes[:third]) + sum(volumes[2 * third:])
            outer_count = len(volumes[:third]) + len(volumes[2 * third:])
            outer_mean = outer_total / outer_count if outer_count > 0 else 0
            if outer_mean > 0 and mid_min < outer_mean * 0.3:
                shape = "B"  # Valley between two clusters = bimodal

    return ProfileShape(shape=shape, skewness=skewness, kurtosis=kurtosis)


def extract_bimodal_lvn(profile: list[VolumeProfileLevel]) -> list[float]:
    """Extract LVN prices from bimodal profile gap zone.

    B-Bimodal shape has two high-volume peaks separated by a low-volume gap.
    The LVN(s) in this gap are the most important entry zones.
    """
    if len(profile) < 5:
        return []

    volumes = [lvl.volume for lvl in profile]
    prices = [lvl.price for lvl in profile]
    n = len(volumes)
    if n == 0:
        return []

    # Find peaks
    peaks = []
    for i in range(1, n - 1):
        if volumes[i] > volumes[i - 1] and volumes[i] > volumes[i + 1]:
            if volumes[i] > max(volumes) * 0.3:  # significant peak
                peaks.append(i)

    if len(peaks) < 2:
        return []

    # Find gap between peaks (LVN zone)
    # Sort peaks by volume descending, take top 2
    peak_vols = [(i, volumes[i]) for i in peaks]
    peak_vols.sort(key=lambda x: -x[1])
    top_2 = sorted([peak_vols[0][0], peak_vols[1][0]])

    # LVN zone = region between the two peaks with minimum volume
    gap_start = top_2[0]
    gap_end = top_2[1]

    # Find minimum volume in gap
    gap_volumes = volumes[gap_start + 1 : gap_end]
    if not gap_volumes:
        return []

    gap_mean = sum(gap_volumes) / len(gap_volumes)
    lvn_prices = []

    for i in range(gap_start + 1, gap_end):
        if volumes[i] < gap_mean * 0.5:  # below 50% of gap average
            lvn_prices.append(prices[i])

    return lvn_prices if lvn_prices else [prices[(gap_start + gap_end) // 2]]


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
            self._poc_history = self._poc_history[-self._max_history :]
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

        return POCMigration(
            direction=direction,
            slope=slope,
            count=n,
            signal=signal,
            poc_vs_price=poc_vs_price,
        )
