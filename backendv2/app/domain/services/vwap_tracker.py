"""Session VWAP tracker with σ bands."""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.trading.model.value_objects import OHLC


@dataclass(frozen=True)
class VWAPResult:
    vwap: float
    std: float
    upper_1: float
    lower_1: float
    upper_2: float
    lower_2: float


class VWAPTracker:
    def __init__(self) -> None:
        self._cum_vol: float = 0.0
        self._cum_quote_vol: float = 0.0
        self._cum_sq_vol: float = 0.0
        self._last_time: str = ""

    def update(self, candle: OHLC) -> VWAPResult:
        typical_price = (float(candle.high) + float(candle.low) + float(candle.close)) / 3
        vol = float(candle.volume)
        quote_vol = typical_price * vol if vol > 0 else 0.0

        reset = False
        if self._last_time:
            try:
                if candle.time[:10] != self._last_time[:10]:
                    reset = True
                elif candle.time < self._last_time:
                    reset = True
            except (TypeError, IndexError):
                reset = False

        if reset:
            self.reset()

        self._last_time = candle.time
        self._cum_vol += vol
        self._cum_quote_vol += float(quote_vol)
        self._cum_sq_vol += float(typical_price * typical_price * vol)

        if self._cum_vol > 0:
            vwap = self._cum_quote_vol / self._cum_vol
            variance = (self._cum_sq_vol / self._cum_vol) - (vwap * vwap)
            std = math.sqrt(max(0.0, variance))
        else:
            vwap = float(candle.close)
            std = 0.0

        return VWAPResult(
            vwap=vwap,
            std=std,
            upper_1=vwap + std,
            lower_1=vwap - std,
            upper_2=vwap + 2 * std,
            lower_2=vwap - 2 * std,
        )

    def reset(self) -> None:
        self._cum_vol = 0.0
        self._cum_quote_vol = 0.0
        self._cum_sq_vol = 0.0

    @property
    def current_vwap(self) -> float:
        if self._cum_vol > 0:
            return self._cum_quote_vol / self._cum_vol
        return 0.0

