"""Absorption detection + clusters — AMT §7.2.

Triple gate per bar: volume >= vol_mult × rolling avg volume, range <=
range_mult × rolling avg range, and one-sided flow >= one_sided_min. The
one-sided fraction comes from the order book when available
(``book_one_sided``); when book data is absent the delta/volume proxy
``|delta| / volume`` is used. Averages are computed over the prior
``avg_window`` bars only, so a spike never inflates its own reference.

Absorption bars whose range sits within 3 ticks of the existing cluster
accumulate into it; cluster high/low bound the absorbed zone.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from quantv2.types import Bar

SELL_ABSORBED = "SELL_ABSORBED"
BUY_ABSORBED = "BUY_ABSORBED"


@dataclass(frozen=True)
class Absorption:
    bar: Bar
    side: str
    vol_ratio: float
    range_ratio: float
    one_sided: float


class AbsorptionTracker:
    def __init__(
        self,
        avg_window: int = 20,
        vol_mult: float = 1.5,
        range_mult: float = 0.5,
        one_sided_min: float = 0.60,
        tick: float = 0.05,
    ) -> None:
        self.avg_window = avg_window
        self.vol_mult = vol_mult
        self.range_mult = range_mult
        self.one_sided_min = one_sided_min
        self.tick = tick
        self._hist: deque[tuple[float, float]] = deque(maxlen=avg_window)
        self._cluster_high: float | None = None
        self._cluster_low: float | None = None
        self._cluster_count = 0

    def on_bar(self, bar: Bar, book_one_sided: float | None = None) -> Absorption | None:
        rng = bar.high - bar.low
        n = len(self._hist)
        if n < self.avg_window:
            self._hist.append((bar.volume, rng))
            return None
        avg_vol = sum(v for v, _ in self._hist) / n
        avg_rng = sum(r for _, r in self._hist) / n
        self._hist.append((bar.volume, rng))
        if avg_vol <= 0 or avg_rng <= 0:
            return None
        vol_ratio = bar.volume / avg_vol
        range_ratio = rng / avg_rng
        if vol_ratio < self.vol_mult or range_ratio > self.range_mult:
            return None
        if book_one_sided is not None:
            one_sided = book_one_sided
        elif bar.volume > 0:
            one_sided = abs(bar.delta) / bar.volume
        else:
            return None
        if one_sided < self.one_sided_min:
            return None
        if bar.delta > 0:
            side = BUY_ABSORBED
        elif bar.delta < 0:
            side = SELL_ABSORBED
        else:
            return None
        self._join_cluster(bar)
        return Absorption(bar, side, vol_ratio, range_ratio, one_sided)

    def cluster(self) -> dict | None:
        if self._cluster_high is None:
            return None
        return {"high": self._cluster_high, "low": self._cluster_low, "count": self._cluster_count}

    def _join_cluster(self, bar: Bar) -> None:
        reach = 3 * self.tick
        if (
            self._cluster_high is not None
            and bar.high >= self._cluster_low - reach
            and bar.low <= self._cluster_high + reach
        ):
            self._cluster_high = max(self._cluster_high, bar.high)
            self._cluster_low = min(self._cluster_low, bar.low)
            self._cluster_count += 1
        else:
            self._cluster_high = bar.high
            self._cluster_low = bar.low
            self._cluster_count = 1
