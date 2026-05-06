"""Tick-level delta classification (Lee–Ready style)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TickDelta:
    price: float
    volume: float
    delta: float
    is_buy: bool
    is_sell: bool
    method: str


class TickDeltaClassifier:
    """Classify tick flow as buy/sell/neutral."""

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
        if volume <= 0 or price <= 0:
            return TickDelta(
                price=price,
                volume=volume,
                delta=0.0,
                is_buy=False,
                is_sell=False,
                method="zero",
            )

        if bid > 0 and ask > 0 and bid < ask:
            if price >= ask:
                result = TickDelta(price, volume, +volume, True, False, "quote")
                self._finalize(price)
                return result
            if price <= bid:
                result = TickDelta(price, volume, -volume, False, True, "quote")
                self._finalize(price)
                return result

        if self._initialized:
            if price > self._prev_price:
                result = TickDelta(price, volume, +volume, True, False, "tick")
            elif price < self._prev_price:
                result = TickDelta(price, volume, -volume, False, True, "tick")
            else:
                result = TickDelta(price, volume, 0.0, False, False, "zero")
            self._finalize(price)
            return result

        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            if price >= mid:
                result = TickDelta(price, volume, +volume, True, False, "tick")
            else:
                result = TickDelta(price, volume, -volume, False, True, "tick")
        else:
            # fallback assumes buy on first tick if no quotes
            result = TickDelta(price, volume, +volume, True, False, "tick")

        self._finalize(price)
        return result

    def reset(self) -> None:
        self._prev_price = 0.0
        self._initialized = False

    def _finalize(self, price: float) -> None:
        self._prev_price = price
        self._initialized = True


def candle_delta_proxy(
    open_: float, high: float, low: float, close: float, volume: float
) -> float:
    spread = high - low
    if spread <= 0 or volume <= 0:
        return 0.0
    body_ratio = (close - open_) / spread
    return body_ratio * volume

