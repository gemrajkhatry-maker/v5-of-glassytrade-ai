"""initial balance engine — AMT analysis service.

Based on amt_docs §2.1 (Initial Balance + Prior Day Levels).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class IBResult:
    """Initial Balance result."""
    high: float = 0.0
    low: float = 0.0
    complete: bool = False
    minutes: int = 0
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0


class InitialBalanceEngine:
    """Track initial balance high/low."""

    def __init__(self, ib_minutes: int = 60):
        self.ib_minutes = ib_minutes
        self._start_time: datetime | None = None
        self._high = 0.0
        self._low = float("inf")
        self._prior_poc = 0.0
        self._prior_vah = 0.0
        self._prior_val = 0.0

    def update(self, timestamp: datetime, price: float) -> IBResult:
        """
        Update IB with new tick.
        
        Args:
            timestamp: Bar timestamp
            price: Bar close price
        
        Returns:
            IBResult with current IB state
        """
        if self._start_time is None:
            self._start_time = timestamp
            self._high = price
            self._low = price
        else:
            self._high = max(self._high, price)
            self._low = min(self._low, price)

        # Check if IB is complete
        elapsed = (timestamp - self._start_time).total_seconds() / 60
        complete = elapsed >= self.ib_minutes

        return IBResult(
            high=self._high,
            low=self._low,
            complete=complete,
            minutes=int(elapsed),
            prior_poc=self._prior_poc,
            prior_vah=self._prior_vah,
            prior_val=self._prior_val,
        )

    def set_prior_levels(self, poc: float, vah: float, val: float) -> None:
        """Set prior day levels."""
        self._prior_poc = poc
        self._prior_vah = vah
        self._prior_val = val

    def reset(self) -> None:
        """Reset IB tracking."""
        self._start_time = None
        self._high = 0.0
        self._low = float("inf")


def calculate_initial_balance(bars: list[dict], minutes: int = 60) -> IBResult:
    """
    Calculate initial balance from bars.
    
    Args:
        bars: List of bar dicts with 'timestamp', 'high', 'low'
        minutes: IB period in minutes
    
    Returns:
        IBResult with IB high/low
    """
    if not bars:
        return IBResult()

    first_time = bars[0].get("timestamp")
    if not first_time:
        return IBResult()
    if isinstance(first_time, (int, float)):
        first_time = float(first_time)

    high = 0.0
    low = float("inf")

    for bar in bars:
        ts = bar.get("timestamp")
        if ts is None:
            continue
        if isinstance(ts, (int, float)):
            elapsed = (float(ts) - first_time) / 60
        elif hasattr(ts, "timestamp"):
            elapsed = (ts - first_time).total_seconds() / 60
        else:
            elapsed = 0
        if ts and first_time:
            if elapsed <= minutes:
                high = max(high, bar.get("high", 0))
                low = min(low, bar.get("low", float("inf")))

    return IBResult(high=high if high else 0, low=low if low != float("inf") else 0)

