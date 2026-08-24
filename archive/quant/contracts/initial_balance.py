"""Initial Balance value object.

Encapsulates first-hour trading range and prior day levels.
Extracted from the flat AMTResult dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InitialBalance:
    """First-hour trading range (Initial Balance).

    Attributes:
        high: Highest price in the first hour.
        low: Lowest price in the first hour.
        complete: Whether the initial balance period has ended.
    """

    high: float = 0.0
    low: float = 0.0
    complete: bool = False

    @property
    def range(self) -> float:
        """Width of the initial balance range."""
        return self.high - self.low if self.high and self.low else 0.0


@dataclass(frozen=True)
class PriorDayLevels:
    """Prior day volume profile reference levels.

    Attributes:
        poc: Prior day Point of Control.
        vah: Prior day Value Area High.
        val: Prior day Value Area Low.
    """

    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0


@dataclass(frozen=True)
class HigherTimeframeLevels:
    """Daily and hourly volume profile levels for multi-timeframe analysis."""

    daily_vah: float = 0.0
    daily_val: float = 0.0
    daily_poc: float = 0.0
    hourly_vah: float = 0.0
    hourly_val: float = 0.0
    hourly_poc: float = 0.0
