from dataclasses import dataclass
from math import sqrt

from quant.bars import Bar


@dataclass(frozen=True)
class VWAPState:
    value: float
    upper_1: float
    lower_1: float
    upper_2: float
    lower_2: float
    std: float
    deviation_sigmas: float


class VWAPBuilder:
    """Volume-weighted average price (VWAP) accumulator using Typical Price (H+L+C)/3.
    
    Harmonized with the AMTAnalyzer decision kernel.
    """

    def __init__(self) -> None:
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self._cum_sq_vol = 0.0
        self._prev_vwap = 0.0
        self._last_close = 0.0
        self._n = 0

    def update(self, bar: Bar) -> None:
        self._n += 1
        self._last_close = float(bar.close)
        vol = float(bar.volume)
        # Typical price (H+L+C)/3 matches the canonical AMT typical-price definition
        tp = (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0 if (bar.high and bar.low) else self._last_close

        if vol > 0:
            self._cum_vol += vol
            self._cum_pv += tp * vol
            new_vwap = self._cum_pv / self._cum_vol
            # Shifted incremental variance: Welford-style accumulation
            self._cum_sq_vol += vol * (tp - self._prev_vwap) * (tp - new_vwap)
            self._prev_vwap = new_vwap

    def snapshot(self) -> VWAPState:
        if self._n == 0:
            return VWAPState(value=0.0, upper_1=0.0, lower_1=0.0,
                             upper_2=0.0, lower_2=0.0, std=0.0,
                             deviation_sigmas=0.0)
        if self._cum_vol <= 0:
            value = self._last_close
            return VWAPState(value=value, upper_1=value, lower_1=value,
                             upper_2=value, lower_2=value, std=0.0,
                             deviation_sigmas=0.0)
        value = self._prev_vwap
        variance = max(0.0, self._cum_sq_vol / self._cum_vol)
        std = sqrt(variance)
        deviation_sigmas = (self._last_close - value) / std if std > 0 else 0.0
        return VWAPState(value=value,
                         upper_1=value + std,
                         lower_1=value - std,
                         upper_2=value + 2 * std,
                         lower_2=value - 2 * std,
                         std=std,
                         deviation_sigmas=deviation_sigmas)

