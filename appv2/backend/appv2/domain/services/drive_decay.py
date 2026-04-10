"""Drive Decay Tracker — monitors D3+ exhaustion patterns.

Tracks:
- Consecutive pushes in same direction (drive count)
- Volume decay on successive drives
- Range contraction on successive drives
- When to expect reversal vs continuation
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriveDecayResult:
    drive_number: int
    is_exhausted: bool
    volume_decay: float  # Ratio of current drive vol to D1 vol
    range_contraction: float  # Ratio of current drive range to D1 range
    reversal_probability: float  # 0.0-1.0
    recommendation: str  # "CONTINUE" | "REDUCE" | "REVERSE"


class DriveDecayTracker:
    """Tracks drive exhaustion patterns."""

    def __init__(self):
        self._drive_volumes: list[float] = []
        self._drive_ranges: list[float] = []
        self._current_drive_vol: float = 0.0
        self._current_drive_range: float = 0.0
        self._drive_count: int = 0
        self._last_direction: str = ""

    def update_drive(
        self,
        direction: str,
        volume: float,
        price_range: float,
    ) -> DriveDecayResult:
        """Update drive tracker with new drive data.

        Args:
            direction: "UP" or "DOWN"
            volume: Cumulative volume of the drive
            price_range: Price range of the drive
        """
        # New drive in same direction
        if direction == self._last_direction:
            self._current_drive_vol += volume
            self._current_drive_range = max(self._current_drive_range, price_range)
        else:
            # Previous drive complete, record it
            if self._drive_count > 0:
                self._drive_volumes.append(self._current_drive_vol)
                self._drive_ranges.append(self._current_drive_range)

            # Start new drive
            self._drive_count += 1
            self._current_drive_vol = volume
            self._current_drive_range = price_range
            self._last_direction = direction

        return self._calculate()

    def _calculate(self) -> DriveDecayResult:
        """Calculate drive decay metrics."""
        if self._drive_count < 1:
            return DriveDecayResult(
                drive_number=self._drive_count,
                is_exhausted=False,
                volume_decay=1.0,
                range_contraction=1.0,
                reversal_probability=0.0,
                recommendation="CONTINUE",
            )

        d1_vol = self._drive_volumes[0] if self._drive_volumes else self._current_drive_vol
        d1_range = self._drive_ranges[0] if self._drive_ranges else self._current_drive_range

        vol_decay = self._current_drive_vol / d1_vol if d1_vol > 0 else 1.0
        range_contraction = self._current_drive_range / d1_range if d1_range > 0 else 1.0

        # D3+ exhaustion
        is_exhausted = self._drive_count >= 3 and vol_decay < 0.5

        # Reversal probability increases with drive count and decay
        reversal_prob = 0.0
        if self._drive_count >= 3:
            reversal_prob = min(1.0, 0.3 + (1 - vol_decay) * 0.4 + (1 - range_contraction) * 0.3)

        # Recommendation
        if is_exhausted:
            recommendation = "REDUCE"
        elif reversal_prob > 0.7:
            recommendation = "REVERSE"
        elif vol_decay > 0.7:
            recommendation = "CONTINUE"
        else:
            recommendation = "REDUCE"

        return DriveDecayResult(
            drive_number=self._drive_count,
            is_exhausted=is_exhausted,
            volume_decay=round(vol_decay, 3),
            range_contraction=round(range_contraction, 3),
            reversal_probability=round(reversal_prob, 3),
            recommendation=recommendation,
        )

    def reset(self) -> None:
        self._drive_volumes.clear()
        self._drive_ranges.clear()
        self._current_drive_vol = 0.0
        self._current_drive_range = 0.0
        self._drive_count = 0
        self._last_direction = ""
