"""drive tracker — AMT analysis service.

Based on FR-05:
- Track drive numbers (D1, D2, D3+)
- Drive entry validation (only D2 with D1 rejected)
- Momentum tracking
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DriveState:
    """Drive tracking state."""
    drive_number: int
    momentum: float
    is_exhausted: bool


class DriveTracker:
    """Track market drives (D1, D2, D3+)."""

    def __init__(self):
        self._drive_number: int = 0
        self._last_level: float | None = None
        self._momentum: float = 0.0
        self._exhausted: bool = False

    def update(self, price: float, level: float, direction: str) -> DriveState:
        """
        Update drive tracking.
        
        Args:
            price: Current price
            level: Key level that was tested
            direction: Price direction ("UP" or "DOWN")
        
        Returns:
            Current drive state
        """
        # Check if we're testing a new level
        if self._last_level is not None and level != self._last_level:
            # New level tested - increment drive number
            self._drive_number += 1
            self._exhausted = self._drive_number >= 3

        # Always update last_level
        self._last_level = level

        # Update momentum
        if direction == "UP":
            self._momentum = min(1.0, self._momentum + 0.1)
        elif direction == "DOWN":
            self._momentum = max(-1.0, self._momentum - 0.1)

        return DriveState(
            drive_number=self._drive_number,
            momentum=self._momentum,
            is_exhausted=self._exhausted,
        )

    def reset(self) -> None:
        """Reset drive tracking."""
        self._drive_number = 0
        self._last_level = None
        self._momentum = 0.0
        self._exhausted = False

    @property
    def drive_number(self) -> int:
        return self._drive_number

