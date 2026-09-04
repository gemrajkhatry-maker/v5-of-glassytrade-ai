from __future__ import annotations


def _linreg_slope(ys: list[float]) -> float:
    """OLS slope for evenly spaced points (v1 quant/amt/compute.py linreg_slope)."""
    n = len(ys)
    if n < 2:
        return 0.0
    x_mean = (n - 1) * 0.5
    y_mean = sum(ys) / n
    num = 0.0
    den = 0.0
    for i in range(n):
        dx = i - x_mean
        num += dx * (ys[i] - y_mean)
        den += dx * dx
    return num / den if den != 0.0 else 0.0


class _EMA:
    """v1-compatible EMA (quant/amt/compute.py): alpha = 2/(period+1), first value seeds."""

    __slots__ = ("_k", "_value", "_seeded")

    def __init__(self, period: int) -> None:
        self._k = 2.0 / (int(period) + 1)
        self._value = 0.0
        self._seeded = False

    def reset(self) -> None:
        self._value = 0.0
        self._seeded = False

    @property
    def value(self) -> float:
        return self._value

    def update(self, x: float) -> None:
        if not self._seeded:
            self._value = x
            self._seeded = True
        else:
            self._value += self._k * (x - self._value)


class CVDTracker:
    """Cumulative Volume Delta with velocity (AMT §6.2) and price/CVD divergence.

    velocity = EMA(ema_fast) − EMA(ema_slow) of the per-bar delta.
    divergence reports the CVD trajectory over `lookback` bars:
    "BULLISH_RISING" (cvd rising), "BEARISH_FALLING" (cvd falling — the
    CVD-kill source when price_trend is "UP"), or "NONE".
    """

    _MAX_HISTORY = 500

    def __init__(self, ema_fast: int = 3, ema_slow: int = 9) -> None:
        self._cvd = 0.0
        self._cvd_hist: list[float] = []
        self._fast = _EMA(ema_fast)
        self._slow = _EMA(ema_slow)

    @property
    def cvd(self) -> float:
        return self._cvd

    @property
    def velocity(self) -> float:
        return self._fast.value - self._slow.value

    def on_delta(self, delta: float) -> float:
        d = float(delta)
        self._cvd += d
        self._cvd_hist.append(self._cvd)
        if len(self._cvd_hist) > self._MAX_HISTORY:
            del self._cvd_hist[: len(self._cvd_hist) - self._MAX_HISTORY]
        self._fast.update(d)
        self._slow.update(d)
        return self.velocity

    def divergence(self, price_trend: str, lookback: int = 6) -> str:
        if str(price_trend).strip().upper() not in ("UP", "DOWN"):
            return "NONE"
        hist = self._cvd_hist
        window = hist[-(int(lookback) + 1) :]
        slope = _linreg_slope(window)
        if slope > 0.0:
            return "BULLISH_RISING"
        if slope < 0.0:
            return "BEARISH_FALLING"
        return "NONE"

    def reset(self) -> None:
        self._cvd = 0.0
        self._cvd_hist.clear()
        self._fast.reset()
        self._slow.reset()
