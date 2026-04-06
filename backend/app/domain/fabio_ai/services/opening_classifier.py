"""Opening Type Classifier — Market Open Auction analysis.

Classifies the opening type based on Fabio/Dalton AMT methodology:
1. OPEN DRIVE: Price moves strongly away from open, no re-test.
2. OPEN TEST REJECTION: Price tests a key level (VAH/VAL/POC), then reverses hard.
3. OPEN REJECTION REVERSE: Price moves one way, fails, then breaks the other extreme.
4. OPEN AUCTION: Price rotates around the open, no direction yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpeningTypeResult:
    type: str  # "OPEN_DRIVE" | "OPEN_TEST_REJECTION" | "OPEN_REJECTION_REVERSE" | "OPEN_AUCTION"
    confidence: float
    description: str


class OpeningTypeClassifier:
    """Classifies the opening auction type using first 15-30 minutes of data."""

    def __init__(self, tick_size: float = 0.05) -> None:
        self._tick_size = tick_size

    def classify(
        self,
        data: list[OHLC],
        prior_vah: float,
        prior_val: float,
        prior_poc: float,
    ) -> OpeningTypeResult:
        """Classify the opening type based on price action and prior levels.

        Requires at least 3-5 candles of 5M data (15-25 mins).
        """
        if not data or len(data) < 3:
            return OpeningTypeResult("OPEN_AUCTION", 0.1, "Insufficent data for classification")

        open_price = float(data[0].open)
        current_price = float(data[-1].close)
        highest = max(float(d.high) for d in data)
        lowest = min(float(d.low) for d in data)
        
        total_range = highest - lowest
        dist_from_open = current_price - open_price
        
        # 1. OPEN DRIVE (Strong move, no look back)
        # Criteria: range is > 1.5x of first candle, and close is at extreme 20% of range
        first_candle_range = float(data[0].high - data[0].low)
        if total_range > first_candle_range * 1.5:
            if current_price > (highest - total_range * 0.2) and lowest >= open_price - self._tick_size * 5:
                # Upward Drive
                return OpeningTypeResult("OPEN_DRIVE", 0.8, "Strong price discovery away from open")
            if current_price < (lowest + total_range * 0.2) and highest <= open_price + self._tick_size * 5:
                # Downward Drive
                return OpeningTypeResult("OPEN_DRIVE", 0.8, "Strong price discovery away from open")

        # 2. OPEN TEST REJECTION
        # Criteria: Price tests prior VA boundary or POC and reverses hard
        levels = [prior_vah, prior_val, prior_poc]
        for level in levels:
            if level <= 0: continue
            
            # Test above then reject
            if highest >= level - self._tick_size * 2 and highest <= level + self._tick_size * 10:
                if current_price < open_price - total_range * 0.4:
                    return OpeningTypeResult("OPEN_TEST_REJECTION", 0.7, f"Rejection at level {level:.2f}")
            
            # Test below then reject
            if lowest <= level + self._tick_size * 2 and lowest >= level - self._tick_size * 10:
                if current_price > open_price + total_range * 0.4:
                    return OpeningTypeResult("OPEN_TEST_REJECTION", 0.7, f"Rejection at level {level:.2f}")

        # 3. OPEN REJECTION REVERSE
        # Criteria: Initial move in one direction, followed by break of initial IB extreme
        first_15_high = max(float(d.high) for d in data[:3])
        first_15_low = min(float(d.low) for d in data[:3])
        
        if len(data) >= 5:
            if current_price > first_15_high and lowest < open_price:
                return OpeningTypeResult("OPEN_REJECTION_REVERSE", 0.6, "Failed initial auction, reversed upward")
            if current_price < first_15_low and highest > open_price:
                return OpeningTypeResult("OPEN_REJECTION_REVERSE", 0.6, "Failed initial auction, reversed downward")

        # 4. OPEN AUCTION (Rotational)
        return OpeningTypeResult("OPEN_AUCTION", 0.4, "Price rotating around opening range")
