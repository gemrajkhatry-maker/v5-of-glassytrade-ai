"""Profile Classifier — shape classification and POC migration tracking.

Shapes:
  D = Bell (balanced distribution)
  P = Top-heavy (distribution at highs, short signal)
  b = Bottom-heavy (accumulation at lows, long signal)
  B = Bimodal (two peaks, transition state)

POC Migration:
  Tracks POC movement across sessions to detect value shift direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from appv2.domain.services.incremental_volume_profile import VolumeProfileLevel


@dataclass
class ProfileShape:
    shape: str  # "D", "P", "b", "B"
    description: str
    poc_migration: str  # "HIGHER" | "LOWER" | "SAME"


def classify_shape(
    profile: list[VolumeProfileLevel],
    poc: float,
    vah: float,
    val: float,
) -> ProfileShape:
    """Classify profile shape from volume distribution.

    Method:
    1. Find HVN and LVN positions
    2. D = single HVN near center, volume tapers symmetrically
    3. P = HVN in upper half, thin volume below
    4. b = HVN in lower half, thin volume above
    5. B = two distinct HVN peaks
    """
    if not profile or poc == 0:
        return ProfileShape(shape="", description="Insufficient data", poc_migration="")

    # Find volume statistics
    vols = [p.volume for p in profile]
    mean_vol = sum(vols) / len(vols) if vols else 0
    max_vol = max(vols) if vols else 0

    # Find HVN position relative to VA
    hvn_prices = [p.price for p in profile if p.volume > mean_vol * 2]
    if not hvn_prices:
        hvn_prices = [poc]

    poc_idx = next((i for i, p in enumerate(profile) if p.price == poc), len(profile) // 2)
    mid_idx = len(profile) // 2

    # Check for bimodal (two distinct peaks)
    peaks = _find_peaks(profile)
    if len(peaks) >= 2:
        return ProfileShape(
            shape="B",
            description="Bimodal — two value areas, transition state",
            poc_migration="",
        )

    # Check P vs b vs D
    if poc_idx < mid_idx - 2:
        # POC in upper half = P-shape (top-heavy)
        return ProfileShape(
            shape="P",
            description="Top-heavy — distribution at highs, potential short",
            poc_migration="",
        )
    elif poc_idx > mid_idx + 2:
        # POC in lower half = b-shape (bottom-heavy)
        return ProfileShape(
            shape="b",
            description="Bottom-heavy — accumulation at lows, potential long",
            poc_migration="",
        )
    else:
        # POC near center = D-shape (bell)
        return ProfileShape(
            shape="D",
            description="Bell shape — balanced distribution",
            poc_migration="",
        )


def _find_peaks(profile: list[VolumeProfileLevel]) -> list[int]:
    """Find local maxima in volume profile."""
    peaks = []
    for i in range(1, len(profile) - 1):
        if profile[i].volume > profile[i - 1].volume and profile[i].volume > profile[i + 1].volume:
            if profile[i].volume > profile[i - 1].volume * 1.5:  # Significant peak
                peaks.append(i)
    return peaks


class POCMigrationTracker:
    """Tracks POC movement across sessions."""

    def __init__(self):
        self._poc_history: list[float] = []

    def update(self, poc: float) -> str:
        """Record POC and return migration direction."""
        self._poc_history.append(poc)

        if len(self._poc_history) < 2:
            return "SAME"

        prev = self._poc_history[-2]
        current = self._poc_history[-1]

        if current > prev * 1.001:  # 0.1% threshold
            return "HIGHER"
        elif current < prev * 0.999:
            return "LOWER"
        return "SAME"

    def reset(self) -> None:
        self._poc_history.clear()
