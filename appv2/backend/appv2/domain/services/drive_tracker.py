"""Drive Tracker — drive numbering (D1, D2, D3+) with rejection tracking.

Tracks directional price moves (drives) from value area.
D1 = first drive away from value
D2 = pullback + continuation
D3+ = extended drives (exhaustion zone)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DriveState:
    drive_number: int  # 0 = no drive, 1 = D1, 2 = D2, 3+ = D3+
    direction: str  # "UP" or "DOWN"
    is_exhausted: bool
    is_suppressed: bool  # D1 couldn't gain momentum
    pullback_depth: float  # How far price pulled back (for D2 detection)


class DriveTracker:
    """Tracks drive progression."""

    def __init__(self):
        self._drive_number: int = 0
        self._direction: str = ""
        self._swing_high: float = 0.0
        self._swing_low: float = float("inf")
        self._pullback_count: int = 0

    def update(self, price: float, is_higher: bool) -> DriveState:
        """Update drive state with new price.

        Args:
            price: Current price.
            is_higher: True if price moved up from previous.
        """
        direction = "UP" if is_higher else "DOWN"

        # New drive in opposite direction
        if direction != self._direction:
            if self._drive_number > 0:
                # Check if pullback is deep enough for next drive
                if self._pullback_count >= 2:
                    self._drive_number = min(self._drive_number + 1, 5)
                else:
                    # Shallow pullback → same drive continues
                    pass
            else:
                self._drive_number = 1

            self._direction = direction
            self._pullback_count = 0

            if direction == "UP":
                self._swing_high = price
            else:
                self._swing_low = price
        else:
            # Same direction
            if direction == "UP":
                if price > self._swing_high:
                    self._swing_high = price
                    self._pullback_count = 0
                else:
                    self._pullback_count += 1
            else:
                if price < self._swing_low:
                    self._swing_low = price
                    self._pullback_count = 0
                else:
                    self._pullback_count += 1

        # D1 suppression check (first drive doesn't go far)
        is_suppressed = self._drive_number == 1 and self._pullback_count >= 3

        # D3+ exhaustion
        is_exhausted = self._drive_number >= 3 and self._pullback_count >= 5

        return DriveState(
            drive_number=self._drive_number,
            direction=self._direction,
            is_exhausted=is_exhausted,
            is_suppressed=is_suppressed,
            pullback_depth=0.0,  # Computed externally
        )

    def reset(self) -> None:
        self._drive_number = 0
        self._direction = ""
        self._swing_high = 0.0
        self._swing_low = float("inf")
        self._pullback_count = 0
