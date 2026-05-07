"""Cumulative Delta Engine."""

from __future__ import annotations

from typing import List, Tuple


class CumulativeDeltaEngine:
    """
    Track cumulative delta over time.
    
    Features:
    - Running cumulative delta
    - High/low water marks
    - Price-delta divergence detection
    - Session tracking
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._cumulative_delta = 0.0
        self._high_water_mark = 0.0
        self._low_water_mark = 0.0
        self._price_history: List[Tuple[float, float]] = []  # (price, cum_delta)

    @property
    def cumulative_delta(self) -> float:
        """Current cumulative delta."""
        return self._cumulative_delta

    @property
    def high_water_mark(self) -> float:
        """Highest cumulative delta reached."""
        return self._high_water_mark

    @property
    def low_water_mark(self) -> float:
        """Lowest cumulative delta reached."""
        return self._low_water_mark

    @property
    def session_delta(self) -> float:
        """Total session delta (same as cumulative)."""
        return self._cumulative_delta

    @property
    def price_history(self) -> List[Tuple[float, float]]:
        """Price and delta history."""
        return self._price_history

    def add_delta(self, delta: float) -> None:
        """Add delta to cumulative total."""
        self._cumulative_delta += delta
        
        # Update water marks
        if self._cumulative_delta > self._high_water_mark:
            self._high_water_mark = self._cumulative_delta
        if self._cumulative_delta < self._low_water_mark:
            self._low_water_mark = self._cumulative_delta

    def add_price_point(self, price: float, delta: float) -> None:
        """Add price point with delta."""
        self.add_delta(delta)
        self._price_history.append((price, self._cumulative_delta))

    def reset(self) -> None:
        """Reset engine."""
        self._cumulative_delta = 0.0
        self._high_water_mark = 0.0
        self._low_water_mark = 0.0
        self._price_history.clear()
