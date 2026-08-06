"""Order-flow metrics: delta, cumulative volume delta (CVD), CVD slope,
close-vs-CVD divergence, and aggressive prints.

Greenfield pure analysis module. No imports from backend/ or app/.
"""
from dataclasses import dataclass

from quant.bars import Bar


@dataclass(frozen=True)
class OrderFlowState:
    delta: float          # latest bar delta (buy - sell)
    cvd: float            # cumulative delta
    cvd_slope: float      # linear slope of last N deltas (N=20)
    cvd_divergence: str   # "BULLISH" | "BEARISH" | "NONE"
    aggressive_prints: tuple[tuple[float, float, str], ...]  # (price, volume, "BUY"/"SELL")


def _linear_slope(ys: list[float]) -> float:
    """Ordinary-least-squares slope of y over x=0..n-1 (n = len(ys))."""
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_xx = sum(x * x for x in xs)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


class OrderFlowBuilder:
    def __init__(self, window: int = 20) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self._window = window
        self._closes: list[float] = []
        self._cvd_history: list[float] = []
        self._cvd: float = 0.0
        self._last_delta: float = 0.0
        self._last: Bar | None = None

    def update(self, bar: Bar) -> None:
        self._last = bar
        self._last_delta = bar.delta
        self._cvd += bar.delta
        self._cvd_history.append(self._cvd)
        self._closes.append(bar.close)

    def snapshot(self) -> OrderFlowState:
        cvd_slope = _linear_slope(self._cvd_history[-self._window:])
        close_slope = _linear_slope(self._closes[-self._window:])
        if cvd_slope > 0 and close_slope < 0:
            divergence = "BULLISH"
        elif cvd_slope < 0 and close_slope > 0:
            divergence = "BEARISH"
        else:
            divergence = "NONE"

        prints: tuple[tuple[float, float, str], ...] = ()
        if self._last is not None:
            bv = self._last.buy_volume
            sv = self._last.sell_volume
            if bv >= 2 * sv:
                prints = ((self._last.close, bv, "BUY"),)
            elif sv >= 2 * bv:
                prints = ((self._last.close, sv, "SELL"),)

        return OrderFlowState(
            delta=self._last_delta,
            cvd=self._cvd,
            cvd_slope=cvd_slope,
            cvd_divergence=divergence,
            aggressive_prints=prints,
        )
