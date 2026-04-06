"""Second Drive Enforcement — tracks structural level touches and pullbacks.

Levels (VAH, VAL, POC, HVN, LVN, AGGRESSIVE_PRINT) progress through:
  UNTOUCHED -> FIRST_TOUCH -> SECOND_DRIVE -> EXHAUSTED

A "drive" requires the price to pull back by at least 1 ATR before returning.
Grade score adjustments: SECOND_DRIVE +2, FIRST_TOUCH -1, EXHAUSTED -2.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackedLevel:
    price: float
    source: str  # "VAH", "VAL", "POC", "HVN", "LVN", "AGGRESSIVE_PRINT"
    touches: list[float] = field(default_factory=list)  # timestamps
    max_pullback: float = 0.0  # largest distance price moved away after touch
    status: str = "UNTOUCHED"  # "UNTOUCHED", "FIRST_TOUCH", "SECOND_DRIVE", "EXHAUSTED"


class LevelTracker:
    """Tracks structural levels and their touch/pullback lifecycle."""

    def __init__(self, proximity_pct: float = 0.003, pullback_atr_mult: float = 1.0):
        self._proximity_pct = proximity_pct
        self._pullback_atr_mult = pullback_atr_mult
        self._levels: dict[float, TrackedLevel] = {}
        self._last_price: float = 0.0

    def register_levels(self, levels: list[tuple[float, str]]) -> None:
        """Register structural levels from AMT. Called when AMT updates."""
        for price, source in levels:
            if price <= 0:
                continue
            # Don't re-register if already tracked at similar price
            if not any(
                abs(price - existing) / existing <= self._proximity_pct
                for existing in self._levels
                if existing > 0
            ):
                self._levels[price] = TrackedLevel(price=price, source=source)

    def update(self, price: float, timestamp: float, atr: float) -> None:
        """Call every tick. Updates touch counts and pullback tracking."""
        for level in self._levels.values():
            proximity = level.price * self._proximity_pct
            near = abs(price - level.price) <= proximity

            if near:
                if level.status == "UNTOUCHED":
                    level.touches.append(timestamp)
                    level.status = "FIRST_TOUCH"
                    level.max_pullback = 0.0
                elif level.status == "FIRST_TOUCH":
                    # Check if price pulled back by 1 ATR and returned
                    if level.max_pullback >= atr * self._pullback_atr_mult:
                        level.touches.append(timestamp)
                        level.status = "SECOND_DRIVE"
                        level.max_pullback = 0.0
                elif level.status == "SECOND_DRIVE":
                    if level.max_pullback >= atr * self._pullback_atr_mult:
                        level.touches.append(timestamp)
                        if len(level.touches) >= 3:
                            level.status = "EXHAUSTED"
            else:
                # Track pullback distance
                if level.status in ("FIRST_TOUCH", "SECOND_DRIVE"):
                    pullback = abs(price - level.price)
                    level.max_pullback = max(level.max_pullback, pullback)

        self._last_price = price

    def get_level_status(self, price: float) -> tuple[str, str] | None:
        """Returns (status, source) for nearest level within proximity, or None."""
        for level in self._levels.values():
            proximity = level.price * self._proximity_pct
            if abs(price - level.price) <= proximity:
                return (level.status, level.source)
        return None

    def clear_intraday(self) -> None:
        """Reset touch tracking. Called at session start."""
        for level in self._levels.values():
            level.touches.clear()
            level.max_pullback = 0.0
            level.status = "UNTOUCHED"


def grade_adjustment_for_level_status(status: str | None) -> int:
    """Return grade score adjustment based on level touch status.

    SECOND_DRIVE: +2 (confirmed level, high-quality entry)
    FIRST_TOUCH: -1 (unconfirmed, reduce confidence)
    EXHAUSTED: -2 (level is spent, avoid)
    """
    if status is None:
        return 0
    if status == "SECOND_DRIVE":
        return 2
    if status == "FIRST_TOUCH":
        return -1
    if status == "EXHAUSTED":
        return -2
    return 0
