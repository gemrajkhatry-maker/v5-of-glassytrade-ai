"""TickDeltaClassifier — Lee-Ready algorithm for real tick-level delta.

Replaces the Gaussian proxy (body-ratio approximation) with the standard
market microstructure algorithm for classifying each trade as buy-initiated
or sell-initiated.

Algorithm:
  STEP 1 — Quote Rule: IF price >= ask → +volume (buyer lifted ask)
                       IF price <= bid → -volume (seller hit bid)
                       IF bid < price < ask → STEP 2
  STEP 2 — Tick Rule:  IF price > prev_price → +volume (uptick)
                       IF price < prev_price → -volume (downtick)
                       IF price = prev_price → 0 (zero-tick)
  STEP 3 — Update state: prev_price = price

References:
  - Lee & Ready (1991) "Inferring Trade Direction from Intraday Data"
  - Standard in market microstructure research
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TickDelta:
    """Output of tick delta classification."""

    price: float
    volume: float
    delta: float  # Signed delta: +volume (buyer), -volume (seller), 0 (unknown)
    is_buy: bool  # True if buyer-initiated
    is_sell: bool  # True if seller-initiated
    method: str  # "quote" or "tick" or "zero"


class TickDeltaClassifier:
    """Lee-Ready tick delta classifier.

    Maintains state (prev_price) across ticks for the tick rule fallback.
    Thread-safe: each symbol gets its own instance.
    """

    def __init__(self) -> None:
        self._prev_price: float = 0.0
        self._initialized: bool = False

    def classify(
        self,
        price: float,
        volume: float,
        bid: float = 0.0,
        ask: float = 0.0,
    ) -> TickDelta:
        """Classify a single trade tick as buy or sell initiated.

        Args:
            price: Trade price
            volume: Trade volume
            bid: Best bid (0.0 if unavailable)
            ask: Best ask (0.0 if unavailable)

        Returns:
            TickDelta with signed delta and classification
        """
        if volume <= 0 or price <= 0:
            return TickDelta(
                price=price,
                volume=volume,
                delta=0.0,
                is_buy=False,
                is_sell=False,
                method="zero",
            )

        # STEP 1: Quote Rule (use when bid/ask available and valid)
        if bid > 0 and ask > 0 and bid < ask:
            if price >= ask:
                return TickDelta(
                    price=price,
                    volume=volume,
                    delta=+volume,
                    is_buy=True,
                    is_sell=False,
                    method="quote",
                )
            if price <= bid:
                return TickDelta(
                    price=price,
                    volume=volume,
                    delta=-volume,
                    is_buy=False,
                    is_sell=True,
                    method="quote",
                )
            # bid < price < ask → ambiguous, go to tick rule

        # STEP 2: Tick Rule (for mid-price trades or missing quote)
        if self._initialized:
            if price > self._prev_price:
                result = TickDelta(
                    price=price,
                    volume=volume,
                    delta=+volume,
                    is_buy=True,
                    is_sell=False,
                    method="tick",
                )
            elif price < self._prev_price:
                result = TickDelta(
                    price=price,
                    volume=volume,
                    delta=-volume,
                    is_buy=False,
                    is_sell=True,
                    method="tick",
                )
            else:
                # Zero-tick — no classification
                result = TickDelta(
                    price=price,
                    volume=volume,
                    delta=0.0,
                    is_buy=False,
                    is_sell=False,
                    method="zero",
                )
        else:
            # First tick — no prev_price, use midpoint heuristic
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                if price >= mid:
                    result = TickDelta(
                        price=price,
                        volume=volume,
                        delta=+volume,
                        is_buy=True,
                        is_sell=False,
                        method="tick",
                    )
                else:
                    result = TickDelta(
                        price=price,
                        volume=volume,
                        delta=-volume,
                        is_buy=False,
                        is_sell=True,
                        method="tick",
                    )
            else:
                # No quote data at all — assume buy on first tick
                result = TickDelta(
                    price=price,
                    volume=volume,
                    delta=+volume,
                    is_buy=True,
                    is_sell=False,
                    method="tick",
                )

        # STEP 3: Update state
        self._prev_price = price
        self._initialized = True

        return result

    def reset(self) -> None:
        """Reset state (call at session open)."""
        self._prev_price = 0.0
        self._initialized = False


def candle_delta_proxy(
    open_: float, high: float, low: float, close: float, volume: float
) -> float:
    """Approximate delta from OHLCV candle when tick data unavailable.

    This is the FALLBACK when real tick data is not available (e.g., historical
    data only). Less accurate than Lee-Ready but works with OHLCV data.

    Formula: delta = (close - open) / (high - low) * volume

    This approximates buyer/seller aggression based on where the close
    falls within the candle range.
    """
    spread = high - low
    if spread <= 0 or volume <= 0:
        return 0.0
    body_ratio = (close - open_) / spread  # -1 to +1
    return body_ratio * volume
