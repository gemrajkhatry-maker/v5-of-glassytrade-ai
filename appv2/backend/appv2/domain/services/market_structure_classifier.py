"""Market Structure Classifier — 5-state model with hysteresis.

States (from Fabio's methodology):
1. BALANCED: Price rotating around POC, 70%+ inside VA
2. INITIATIVE_IMBALANCE: Breakout with acceptance — trending
3. RESPONSIVE_IMBALANCE: Failed breakout, snapping back
4. EXCESS: Extreme move, climactic volume — exhaustion
5. TRANSITION: Between states — wait for clarity

Hysteresis prevents rapid state flipping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StructureState(str, Enum):
    BALANCED = "BALANCED"
    INITIATIVE_IMBALANCE = "INITIATIVE_IMBALANCE"
    RESPONSIVE_IMBALANCE = "RESPONSIVE_IMBALANCE"
    EXCESS = "EXCESS"
    TRANSITION = "TRANSITION"


@dataclass(frozen=True)
class StructureResult:
    state: StructureState
    balance_ratio: float
    trend_direction: str  # "UP" | "DOWN" | "NONE"
    confidence: float
    bars_in_state: int


class MarketStructureClassifier:
    """5-state market structure classifier with hysteresis."""

    def __init__(self, hysteresis_bars: int = 3):
        """
        Args:
            hysteresis_bars: Minimum bars before state can change
        """
        self._hysteresis = hysteresis_bars
        self._state = StructureState.TRANSITION
        self._bars_in_state = 0
        self._balance_ratios: list[float] = []

    def update(
        self,
        price: float,
        poc: float,
        vah: float,
        val: float,
        balance_ratio: float,
        volume: float,
        avg_volume: float,
    ) -> StructureResult:
        """Update structure state with new candle data.

        Args:
            price: Current price (close)
            poc: Point of Control
            vah: Value Area High
            val: Value Area Low
            balance_ratio: % of recent candles inside VA
            volume: Current volume
            avg_volume: Average volume
        """
        self._balance_ratios.append(balance_ratio)
        if len(self._balance_ratios) > 20:
            self._balance_ratios.pop(0)

        new_state = self._classify(price, poc, vah, val, balance_ratio, volume, avg_volume)

        # Apply hysteresis
        if new_state != self._state:
            self._bars_in_state += 1
            if self._bars_in_state >= self._hysteresis:
                self._state = new_state
                self._bars_in_state = 0
        else:
            self._bars_in_state = 0

        return self._build_result(price, poc, vah, val)

    def _classify(
        self, price, poc, vah, val, balance_ratio, volume, avg_volume
    ) -> StructureState:
        """Classify current market structure."""
        inside_va = val <= price <= vah
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        # EXCESS: Extreme volume spike + price at extreme
        if vol_ratio > 3.0 and (abs(price - vah) < (vah - val) * 0.05 or
                                abs(price - val) < (vah - val) * 0.05):
            return StructureState.EXCESS

        # INITIATIVE_IMBALANCE: Outside VA with acceptance + volume
        if not inside_va and balance_ratio < 0.30 and vol_ratio > 1.5:
            return StructureState.INITIATIVE_IMBALANCE

        # RESPONSIVE_IMBALANCE: Failed breakout, back inside VA
        if inside_va and balance_ratio < 0.50 and vol_ratio < 0.8:
            return StructureState.RESPONSIVE_IMBALANCE

        # BALANCED: Inside VA with good balance ratio
        if inside_va and balance_ratio > 0.50:
            return StructureState.BALANCED

        return StructureState.TRANSITION

    def _build_result(self, price, poc, vah, val) -> StructureResult:
        """Build result with direction."""
        avg_balance = (
            sum(self._balance_ratios) / len(self._balance_ratios)
            if self._balance_ratios else 0
        )

        direction = "NONE"
        if self._state == StructureState.INITIATIVE_IMBALANCE:
            direction = "UP" if price > poc else "DOWN"
        elif self._state == StructureState.RESPONSIVE_IMBALANCE:
            direction = "DOWN" if price > poc else "UP"

        confidence = min(1.0, avg_balance) if self._state == StructureState.BALANCED else 0.7

        return StructureResult(
            state=self._state,
            balance_ratio=round(avg_balance, 3),
            trend_direction=direction,
            confidence=round(confidence, 3),
            bars_in_state=self._bars_in_state,
        )

    @property
    def current_state(self) -> StructureState:
        return self._state

    def reset(self) -> None:
        self._state = StructureState.TRANSITION
        self._bars_in_state = 0
        self._balance_ratios.clear()
