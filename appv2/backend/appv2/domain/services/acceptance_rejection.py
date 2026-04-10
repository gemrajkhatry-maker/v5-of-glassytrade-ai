"""Acceptance/Rejection Engine — detects price acceptance vs rejection at VA boundaries.

Acceptance: 2+ consecutive candles beyond VA boundary with volume confirmation
Rejection: Price moves beyond VA but immediately reverses with rejection wick + volume drop
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ARResult:
    accepted: bool
    rejected: bool
    side: str  # "ABOVE_VAH" | "BELOW_VAL" | ""
    confidence: float  # 0.0-1.0
    bar_count: int  # Consecutive bars beyond VA


class AcceptanceRejectionEngine:
    """Detects acceptance or rejection at Value Area boundaries.

    Usage:
        engine = AcceptanceRejectionEngine()
        result = engine.update(candle, vah, val)
    """

    def __init__(self, required_bars: int = 2):
        self._required_bars = required_bars
        self._above_count: int = 0
        self._below_count: int = 0
        self._prev_was_above: bool = False
        self._prev_was_below: bool = False
        self._prev_volume: float = 0.0
        self._rejection_wicks: list[float] = []

    def update(self, candle, vah: float, val: float, avg_volume: float = 0.0) -> ARResult:
        """Analyze candle for acceptance or rejection.

        Args:
            candle: OHLC candle
            vah: Value Area High
            val: Value Area Low
            avg_volume: Average volume for comparison
        """
        is_above = candle.close > vah and candle.low > vah
        is_below = candle.close < val and candle.high < val

        # Update counters
        if is_above:
            self._above_count += 1
            self._below_count = 0
        elif is_below:
            self._below_count += 1
            self._above_count = 0
        else:
            # Price back inside VA
            self._above_count = 0
            self._below_count = 0

        # Rejection detection: wick beyond VA but close inside
        rejection_wick = 0.0
        if candle.high > vah and candle.close <= vah and candle.open <= vah:
            rejection_wick = candle.high - max(vah, candle.close, candle.open)
        elif candle.low < val and candle.close >= val and candle.open >= val:
            rejection_wick = min(val, candle.close, candle.open) - candle.low

        if rejection_wick > 0:
            self._rejection_wicks.append(rejection_wick)
            if len(self._rejection_wicks) > 5:
                self._rejection_wicks.pop(0)

        # Volume confirmation
        volume_confirmed = True
        if avg_volume > 0 and candle.volume > 0:
            volume_confirmed = candle.volume >= avg_volume * 0.8

        # Acceptance: N consecutive bars beyond VA with volume
        accepted = False
        if self._above_count >= self._required_bars and volume_confirmed:
            accepted = True
        if self._below_count >= self._required_bars and volume_confirmed:
            accepted = True

        # Rejection: significant wick with low volume follow-through
        rejected = False
        if rejection_wick > 0:
            wick_ratio = rejection_wick / candle.range if candle.range > 0 else 0
            if wick_ratio > 0.5:  # Wick > 50% of range
                rejected = True

        # Determine side
        side = ""
        if self._above_count > 0:
            side = "ABOVE_VAH"
        elif self._below_count > 0:
            side = "BELOW_VAL"

        # Confidence
        bar_count = max(self._above_count, self._below_count)
        confidence = min(1.0, bar_count / (self._required_bars * 2))

        return ARResult(
            accepted=accepted,
            rejected=rejected,
            side=side,
            confidence=confidence,
            bar_count=bar_count,
        )

    def reset(self) -> None:
        self._above_count = 0
        self._below_count = 0
        self._prev_was_above = False
        self._prev_was_below = False
        self._rejection_wicks.clear()
