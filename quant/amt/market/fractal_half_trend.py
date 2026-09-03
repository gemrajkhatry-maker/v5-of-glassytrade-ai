"""Fractal Half-Trend Detector (ChartArt's Fractal Breakout Strategy port).

Faithful implementation of ChartArt's "Fractal Breakout Strategy" Pine Script
(v2, overlay) — the trend/signal side of it. The strategy:

- detects fractal TOPS: a bar whose ``high`` is the highest of the 5-bar
  window centered on it. In Pine the condition
  ``high[2] > high[3] and high[2] > high[4] and high[2] > high[1] and high[2] > high[0]``
  becomes true on the bar TWO bars after the peak (the confirmation bar),
  because the peak needs both right-hand neighbours to have closed lower;
- anchors a price series at each fractal: ``fractal_price =
  valuewhen(fractal_top, price, 1)`` where the default price type is
  ``hl2 = (high + low) / 2`` — the "half" price. Pine's ``occurrence=1``
  makes this the SECOND most recent fractal-top price, so the series always
  lags the newest fractal by one (a built-in repainting guard);
- computes the FRACTAL TREND from the average of that fractal-price series
  over the prior 2 (or 3) bars: ``fractal_average =
  (fractal_price[1] + fractal_price[2]) / 2`` (or over [1..3] for the
  "longer average" option); trend is UP while that average is strictly
  rising (``fractal_trend = fractal_average[0] > fractal_average[1]``);
- detects a FRACTAL BREAKOUT in no-repainting mode:
  ``fractal_breakout = price[1] > fractal_price[0]`` — the previous bar's
  half-price above the fractal-price series value;
- trade_entry = trend UP and breakout (BUY label on the UI);
- trade_exit = the trend was UP ``n_time`` bars ago but has flipped down
  (lower-highs regime) — the SELL label on the UI for this long-only
  strategy.

All calculation happens here in the backend; the frontend only renders the
BUY / SELL / trend labels from the emitted DTO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import FloatOHLC, OHLC


@dataclass(frozen=True)
class FractalHalfTrendResult:
    """Immutable result of fractal half-trend analysis for one bar."""

    # True when a fractal TOP confirmed on this bar.
    fractal_top: bool = False
    # Pine fractal_price series value (= valuewhen(fractal_top, price, 1),
    # the second most recent fractal top price).
    last_fractal_price: float = 0.0
    # Average of the fractal-price series over the prior 2/3 bars
    # (Pine: fractal_average).
    fractal_average: float = 0.0
    # Trend state — True while the fractal average is rising (Pine:
    # fractal_trend = fractal_average[0] > fractal_average[1]).
    fractal_trend: bool = False
    # Breakout: previous bar's price above the fractal price (Pine:
    # fractal_breakout = price[1] > fractal_price[0], no-repainting mode).
    fractal_breakout: bool = False
    # strategy.entry — trend UP + breakout (BUY label on the UI).
    buy_signal: bool = False
    # strategy.close — trend was UP n_time bars ago, now flipped (SELL label
    # on the UI; long-only strategy, so the exit is the "sell" event).
    sell_signal: bool = False


class FractalHalfTrendDetector:
    """Stateful detector for ChartArt's fractal-top trend and breakout.

    Feed every newly closed bar via :meth:`update`. State (fractal history,
    per-bar series history) is kept internally, matching Pine's series
    history semantics.
    """

    def __init__(
        self,
        n_time: int = 3,
        use_longer_average: bool = True,
    ) -> None:
        self.n_time = max(1, int(n_time))
        self.use_longer_average = bool(use_longer_average)
        self.reset()

    def reset(self) -> None:
        """Reset all rolling state (called on session/day rollover)."""
        # Confirmed fractal-top prices, oldest -> newest. Each value is the
        # hl2 of the bar on which the fractal CONFIRMED (Pine: valuewhen
        # samples `price` on the bar where fractal_top is true).
        self._fractal_prices: list[float] = []
        # Per-bar fractal_price series (Pine: fractal_price).
        self._fps_history: list[float] = []
        # Per-bar fractal_average series (Pine: fractal_average).
        self._average_history: list[float] = []
        # Per-bar trend series (Pine: fractal_trend), for the n_time exit.
        self._trend_history: list[bool] = []
        # Recent highs, oldest -> newest, for the 5-bar fractal window.
        self._highs: list[float] = []
        self._prev_bar: "OHLC | FloatOHLC | None" = None

    def update(self, candle: "OHLC | FloatOHLC") -> FractalHalfTrendResult:
        """Process one newly closed bar and evaluate the fractal trend.

        Args:
            candle: The just-closed bar (OHLC or FloatOHLC).
        """
        high = float(candle.high)
        low = float(candle.low)

        # Pine's default price type: hl2 = (high + low) / 2 — the "half" price.
        price = (high + low) / 2.0

        # ── fractal_top detection ─────────────────────────────────────────
        # Pine evaluates fractal_top on the live bar: high[2] is the peak
        # candidate, high[3]/high[4] its left neighbours, high[1]/high[0]
        # its right neighbours. With the current bar appended, the candidate
        # sits three positions from the end of _highs.
        self._highs.append(high)
        if len(self._highs) > 8:
            self._highs = self._highs[-8:]

        fractal_top = False
        if len(self._highs) >= 5:
            candidate = self._highs[-3]
            right1 = self._highs[-2]
            right2 = self._highs[-1]
            left1 = self._highs[-4]
            left2 = self._highs[-5]
            fractal_top = (
                candidate > left2
                and candidate > left1
                and candidate > right1
                and candidate > right2
            )
        if fractal_top:
            self._fractal_prices.append(price)
        if len(self._fractal_prices) > 256:
            self._fractal_prices = self._fractal_prices[-256:]

        # ── fractal_price (Pine: valuewhen(fractal_top, price, 1)) ────────
        # Occurrence 1 = the SECOND most recent fractal-top price. Before a
        # second fractal exists Pine returns na, mirrored here by 0.0 (all
        # downstream comparisons treat na as false).
        fractal_price = (
            self._fractal_prices[-2] if len(self._fractal_prices) >= 2 else 0.0
        )
        self._fps_history.append(fractal_price)
        if len(self._fps_history) > 512:
            self._fps_history = self._fps_history[-512:]

        # ── fractal_average (Pine: mean of fractal_price[1..2] or [1..3]) ─
        # Offsets [1..count] look at PRIOR bars of the fractal_price series
        # (na poisons the average in Pine — mirrored by requiring every
        # sampled bar to carry a fractal price > 0).
        count = 3 if self.use_longer_average else 2
        window = self._fps_history[-(count + 1):-1]
        fractal_average = 0.0
        if len(window) == count and all(p > 0 for p in window):
            fractal_average = sum(window) / count
        self._average_history.append(fractal_average)
        if len(self._average_history) > 512:
            self._average_history = self._average_history[-512:]

        # ── fractal_trend (Pine: fractal_average[0] > fractal_average[1]) ─
        trend = False
        if len(self._average_history) >= 2:
            prev_avg = self._average_history[-2]
            trend = fractal_average > 0 and prev_avg > 0 and fractal_average > prev_avg
        self._trend_history.append(trend)
        if len(self._trend_history) > 512:
            self._trend_history = self._trend_history[-512:]

        # ── fractal_breakout (no-repainting: price[1] > fractal_price[0]) ─
        # price[1] = previous bar's half-price; fractal_price[0] = this bar's
        # fractal_price series value.
        breakout = False
        if fractal_price > 0 and self._prev_bar is not None:
            prev_price = (
                float(self._prev_bar.high) + float(self._prev_bar.low)
            ) / 2.0
            breakout = prev_price > fractal_price

        # ── Entry / exit (long-only strategy) ─────────────────────────────
        # trade_entry = fractal_trend and fractal_breakout
        buy_signal = bool(trend and breakout)
        # trade_exit = fractal_trend[n_time] and fractal_trend == false
        # (na fractal_trend[n_time] on warmup bars -> false in Pine).
        sell_signal = False
        if len(self._trend_history) > self.n_time:
            trend_n_ago = self._trend_history[-1 - self.n_time]
            if trend_n_ago and not trend:
                sell_signal = True

        self._prev_bar = candle

        return FractalHalfTrendResult(
            fractal_top=fractal_top,
            last_fractal_price=fractal_price,
            fractal_average=fractal_average,
            fractal_trend=trend,
            fractal_breakout=breakout,
            buy_signal=buy_signal,
            sell_signal=sell_signal,
        )
