"""Delta engine — vertical/horizontal/cumulative delta and rate-of-change.

Pure-Python (no numpy): slope is a two-pass least-squares fit, keeping the
analytics core dependency-light. Consumes ``OrderflowCandle`` or raw ``Quote``
events; aggressor side for quotes comes from ``classify_aggressor``.
"""

from __future__ import annotations

from collections import defaultdict

from tradex_domain.market import Quote

from tradex_trading.analytics.orderflow import classify_aggressor, round_price
from tradex_trading.analytics.orderflow_types import DeltaSnapshot, OrderflowCandle


def _slope(values: list[float]) -> float:
    """Least-squares slope over an evenly-spaced series (x = 0..n-1)."""
    n = len(values)
    if n < 2:
        return 0.0
    sx = n * (n - 1) / 2.0
    sxx = n * (n - 1) * (2 * n - 1) / 6.0
    sy = sum(values)
    sxy = sum(i * v for i, v in enumerate(values))
    denom = n * sxx - sx * sx
    if denom == 0.0:
        return 0.0
    return (n * sxy - sx * sy) / denom


class DeltaEngine:
    """Computes delta metrics used for absorption/initiative/divergence detection.

    - vertical delta: total aggressive buys - sells per bar
    - horizontal delta: buy - sell at each price level
    - cumulative delta: running sum across bars (divergence detection)
    """

    def __init__(self, tick_size: float = 0.05, max_history: int = 500) -> None:
        self.tick_size = tick_size
        self._cumulative_delta = 0.0
        self._history: list[DeltaSnapshot] = []
        self._max_history = max_history

    def reset(self) -> None:
        self._cumulative_delta = 0.0
        self._history.clear()

    def compute_from_candle(self, candle: OrderflowCandle) -> DeltaSnapshot:
        """Compute delta from an orderflow-enriched candle."""
        buy_vol = candle.buy_volume
        sell_vol = candle.sell_volume
        vertical = buy_vol - sell_vol
        self._cumulative_delta += vertical

        h_delta: dict[float, float] = {}
        max_delta = float("-inf")
        min_delta = float("inf")
        max_price: float | None = None
        min_price: float | None = None
        for price, fp in candle.footprint.items():
            d = fp.delta
            h_delta[price] = d
            if d > max_delta:
                max_delta, max_price = d, price
            if d < min_delta:
                min_delta, min_price = d, price

        total = buy_vol + sell_vol
        return self._record(
            DeltaSnapshot(
                vertical_delta=vertical,
                cumulative_delta=self._cumulative_delta,
                horizontal_delta=h_delta,
                max_delta_price=max_price,
                min_delta_price=min_price,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                delta_pct=vertical / total if total > 0 else 0.0,
            )
        )

    def compute_from_quotes(
        self, quotes: list[Quote], tick_size: float | None = None
    ) -> DeltaSnapshot:
        """Compute delta from a window of quote events (no candle aggregation)."""
        ts = tick_size or self.tick_size
        h_delta: dict[float, float] = defaultdict(float)
        buy_vol = 0.0
        sell_vol = 0.0

        for q in quotes:
            if q.volume is None:
                continue
            ltp = float(q.ltp.value)
            bid = float(q.bid.value) if q.bid is not None else ltp
            ask = float(q.ask.value) if q.ask is not None else ltp
            vol = float(q.volume.value)
            direction = classify_aggressor(ltp=ltp, bid=bid, ask=ask)
            if direction == 0:
                continue
            rounded = round_price(ltp, ts)
            if direction > 0:
                buy_vol += vol
                h_delta[rounded] += vol
            else:
                sell_vol += vol
                h_delta[rounded] -= vol

        vertical = buy_vol - sell_vol
        self._cumulative_delta += vertical
        max_price = max(h_delta, key=h_delta.__getitem__) if h_delta else None
        min_price = min(h_delta, key=h_delta.__getitem__) if h_delta else None
        total = buy_vol + sell_vol
        return self._record(
            DeltaSnapshot(
                vertical_delta=vertical,
                cumulative_delta=self._cumulative_delta,
                horizontal_delta=dict(h_delta),
                max_delta_price=max_price,
                min_delta_price=min_price,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                delta_pct=vertical / total if total > 0 else 0.0,
            )
        )

    def _record(self, snapshot: DeltaSnapshot) -> DeltaSnapshot:
        self._history.append(snapshot)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        return snapshot

    @property
    def cumulative_delta(self) -> float:
        return self._cumulative_delta

    @property
    def history(self) -> list[DeltaSnapshot]:
        return self._history

    def get_delta_roc(self, lookback: int = 5) -> float:
        """Slope of vertical delta over the last N bars."""
        return _slope([d.vertical_delta for d in self._history[-lookback:]])

    def get_volume_trend(self, lookback: int = 5) -> float:
        """Slope of total volume over the last N bars (declining = exhaustion)."""
        return _slope(
            [d.buy_volume + d.sell_volume for d in self._history[-lookback:]]
        )

    def detect_delta_peaks(
        self, lookback: int = 20
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """Local peaks/troughs of cumulative delta over the last N bars.

        Returns ``(peaks, troughs)`` as ``(index, cumulative_delta)`` pairs.
        """
        cd = [d.cumulative_delta for d in self._history[-lookback:]]
        if len(cd) < 3:
            return [], []
        peaks: list[tuple[int, float]] = []
        troughs: list[tuple[int, float]] = []
        for i in range(1, len(cd) - 1):
            if cd[i] > cd[i - 1] and cd[i] > cd[i + 1]:
                peaks.append((i, cd[i]))
            elif cd[i] < cd[i - 1] and cd[i] < cd[i + 1]:
                troughs.append((i, cd[i]))
        return peaks, troughs


__all__ = ["DeltaEngine"]
