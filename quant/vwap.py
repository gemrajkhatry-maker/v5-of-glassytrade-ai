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
    def __init__(self) -> None:
        self._cum_pv = 0.0
        self._cum_vol = 0.0
        self._cum_sq_vol = 0.0
        self._prev_vwap = 0.0
        self._last_close = 0.0
        self._n = 0

    def update(self, bar: Bar) -> None:
        self._n += 1
        self._last_close = bar.close
        self._cum_vol += bar.volume
        self._cum_pv += bar.close * bar.volume
        if self._cum_vol > 0:
            new_vwap = self._cum_pv / self._cum_vol
            self._cum_sq_vol += bar.volume * (bar.close - self._prev_vwap) * (bar.close - new_vwap)
            self._prev_vwap = new_vwap

    def snapshot(self) -> VWAPState:
        if self._n == 0:
            return VWAPState(value=0.0, upper_1=0.0, lower_1=0.0,
                             upper_2=0.0, lower_2=0.0, std=0.0,
                             deviation_sigmas=0.0)
        value = self._prev_vwap
        std = sqrt(max(0.0, self._cum_sq_vol / self._cum_vol)) if self._cum_vol > 0 else 0.0
        deviation_sigmas = (self._last_close - value) / max(std, 1e-9)
        return VWAPState(value=value,
                         upper_1=value + std,
                         lower_1=value - std,
                         upper_2=value + 2 * std,
                         lower_2=value - 2 * std,
                         std=std,
                         deviation_sigmas=deviation_sigmas)
