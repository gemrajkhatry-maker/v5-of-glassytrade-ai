"""HalfTrend detector (everget, Pine v6, GPL-3.0) — faithful port.

HalfTrend is a trend-following state machine over fractal rails:

- ``amplitude`` (default 2): lookback for the channel extrema and SMAs —
  ``highPrice`` = highest high of the last ``amplitude`` bars,
  ``lowPrice`` = lowest low, ``highma``/``lowma`` = SMAs of high/low.
- ``channelDeviation`` (default 2) * ``atr2`` (where ``atr2 =
  ta.atr(100) / 2``) sets the channel width around the trend line.
- While ``nextTrend == 1`` (expecting a down move) it ratchets
  ``maxLowPrice = max(lowPrice, maxLowPrice)``; a down trend begins when
  ``highma < maxLowPrice and close < low[1]``. While ``nextTrend == 0`` it
  ratchets ``minHighPrice = min(highPrice, minHighPrice)``; an up trend
  begins when ``lowma > minHighPrice and close > high[1]``.
- ``ht`` (the plotted line) is the ``up`` rail in an up trend and the
  ``down`` rail in a down trend; rails ratchet with ``maxLowPrice`` /
  ``minHighPrice`` between flips and re-anchor to the opposite rail on a
  flip (``up := down[1]`` / ``down := up[1]``).
- Arrows are planted at a flip at ``up - atr2`` (Buy, at the channel low)
  or ``down + atr2`` (Sell, at the channel high); signals are exactly the
  flip bars: ``buySignal = trend == 0 and trend[1] == 1`` and the mirror.

na semantics follow Pine: before the first ``atr_period`` true ranges the
ATR (and therefore channel/deviation/arrows) is not available, and
``trend[1]``-based guards keep the flip branch from firing twice.

Display-only: this module never affects decisions, gates, risk, or orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import FloatOHLC, OHLC


@dataclass(frozen=True)
class HalfTrendResult:
    """Immutable result of HalfTrend analysis for one closed bar."""

    time: str
    trend: int  # 0 = up trend (Buy regime), 1 = down trend (Sell regime)
    ht: float  # the HalfTrend line value
    atr_high: float | None = None  # ht + dev (null before ATR warm-up)
    atr_low: float | None = None  # ht - dev (null before ATR warm-up)
    buy_signal: bool = False
    sell_signal: bool = False


class _Rma:
    """Pine rma(x, length): Wilder EMA (alpha = 1/length), SMA-seeded.

    Mirrors ``ta.atr(period)`` which is ``rma(tr, period)``.
    """

    __slots__ = ("period", "_seeded", "_value", "_seed", "_count")

    def __init__(self, period: int) -> None:
        self.period = max(2, int(period))
        self._seeded = False
        self._value = 0.0
        self._seed = 0.0
        self._count = 0

    def update(self, x: float) -> float | None:
        if not self._seeded:
            self._seed += x
            self._count += 1
            if self._count >= self.period:
                # Pine outputs the SMA seed on the bar that completes the
                # lookback (bar index length-1), not the bar after.
                self._value = self._seed / self.period
                self._seeded = True
                return self._value
            return None
        alpha = 1.0 / self.period
        self._value += alpha * (x - self._value)
        return self._value

    def value(self) -> float | None:
        return self._value if self._seeded else None


class HalfTrendDetector:
    """Stateful HalfTrend machine, fed one closed bar per ``update()``.

    ``update`` is idempotent per bar time (repeated analyze calls on the
    same closed bar cannot double-advance the machine). Call
    ``warm_up(candles)`` once over the seed history so the live tail extends
    the same series the stateless ``compute_half_trend_series`` produces.
    """

    def __init__(
        self,
        amplitude: int = 2,
        channel_deviation: int = 2,
        atr_period: int = 100,
    ) -> None:
        self.amplitude = max(1, int(amplitude))
        self.channel_deviation = max(1, int(channel_deviation))
        self.atr_period = max(2, int(atr_period))
        self.reset()

    def reset(self) -> None:
        """Reset the machine to its bar-0 state."""
        self._trend = 0
        self._next_trend = 0
        self._max_low_price: float | None = None
        self._min_high_price: float | None = None
        self._up: float | None = None
        self._down: float | None = None
        self._atr_high: float | None = None
        self._atr_low: float | None = None
        # history of rails/trend for [1] references
        self._prev_trend: int | None = None
        self._prev_up: float | None = None
        self._prev_down: float | None = None
        self._prev_bar: "OHLC | FloatOHLC | None" = None
        self._last_time: str = ""
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._rma = _Rma(self.atr_period)
        self._trs: list[float] = []
        self._last_result: HalfTrendResult | None = None
        self._warmed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warm_up(self, candles: list) -> None:
        """Replay a closed-bar history to bring state to its last bar.

        Used once at seed time so the live per-bar updates continue the
        series that ``compute_half_trend_series`` would produce over the
        same candles.
        """
        if self._warmed or len(candles) < 2:
            return
        self.reset()
        for c in candles[:-1]:
            self.update(c)
        self._warmed = True

    def update(self, candle: "OHLC | FloatOHLC") -> HalfTrendResult:
        """Process one closed bar; returns the HalfTrend row for it."""
        time_str = str(candle.time)
        if time_str and time_str == self._last_time:
            if self._last_result is not None:
                return self._last_result
        high = float(candle.high)
        low = float(candle.low)
        close = float(candle.close)

        # nz(low[1], low) / nz(high[1], high): fall back to the current bar
        # only on the very first processed bar.
        prev_low = float(self._prev_bar.low) if self._prev_bar is not None else low
        prev_high = float(self._prev_bar.high) if self._prev_bar is not None else high
        if self._prev_bar is None:
            # Pine seeds the rails at bar 0 with nz(..., current):
            # maxLowPrice = low[0], minHighPrice = high[0]
            self._max_low_price = low
            self._min_high_price = high

        # Rolling windows (include the current bar, like Pine).
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        if len(self._highs) > self.amplitude:
            self._highs = self._highs[-self.amplitude :]
        if len(self._lows) > self.amplitude:
            self._lows = self._lows[-self.amplitude :]
        if len(self._closes) > self.amplitude:
            self._closes = self._closes[-self.amplitude :]

        # ATR(period) = rma(tr, period); TR is undefined on the first bar.
        atr2: float | None = None
        if self._prev_bar is not None:
            prev_close = float(self._prev_bar.close)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            self._trs.append(tr)
            if len(self._trs) > self.atr_period:
                self._trs = self._trs[-self.atr_period :]
            rma_val = self._rma.update(tr)
            if rma_val is not None:
                atr2 = rma_val / 2.0
        dev = (
            self.channel_deviation * atr2
            if atr2 is not None
            else None
        )

        # Channel extrema + SMAs need a full amplitude window.
        window_ready = len(self._highs) >= self.amplitude
        high_price = max(self._highs) if window_ready else high
        low_price = min(self._lows) if window_ready else low
        highma = sum(self._highs) / len(self._highs) if window_ready else None
        lowma = sum(self._lows) / len(self._lows) if window_ready else None

        # ── rail tracking + trend flip (order = Pine) ─────────────────────
        if self._next_trend == 1:
            self._max_low_price = (
                max(low_price, self._max_low_price)
                if self._max_low_price is not None
                else low_price
            )
            if (
                highma is not None
                and self._max_low_price is not None
                and highma < self._max_low_price
                and close < prev_low
            ):
                self._trend = 1
                self._next_trend = 0
                self._min_high_price = high_price
        else:
            self._min_high_price = (
                min(high_price, self._min_high_price)
                if self._min_high_price is not None
                else high_price
            )
            if (
                lowma is not None
                and self._min_high_price is not None
                and lowma > self._min_high_price
                and close > prev_high
            ):
                self._trend = 0
                self._next_trend = 1
                self._max_low_price = low_price

        # ── up/down rails + arrows (uses trend[1]/up[1]/down[1]) ──────────
        arrow_up: float | None = None
        arrow_down: float | None = None
        prev_trend = self._prev_trend  # trend[1]
        if self._trend == 0:
            if prev_trend is not None and prev_trend != 0:
                # just flipped into an up trend: up := na(down[1]) ? down : down[1]
                self._up = self._prev_down if self._prev_down is not None else 0.0
                if atr2 is not None:
                    arrow_up = self._up - atr2
            else:
                # up := na(up[1]) ? maxLowPrice : max(maxLowPrice, up[1])
                base = self._max_low_price if self._max_low_price is not None else 0.0
                self._up = base if self._prev_up is None else max(base, self._prev_up)
            up_val = self._up
            self._atr_high = up_val + dev if dev is not None else None
            self._atr_low = up_val - dev if dev is not None else None
        else:
            if prev_trend is not None and prev_trend != 1:
                # just flipped into a down trend: down := na(up[1]) ? up : up[1]
                self._down = self._prev_up if self._prev_up is not None else 0.0
                if atr2 is not None:
                    arrow_down = self._down + atr2
            else:
                # down := na(down[1]) ? minHighPrice : min(minHighPrice, down[1])
                base = self._min_high_price if self._min_high_price is not None else 0.0
                self._down = base if self._prev_down is None else min(base, self._prev_down)
            down_val = self._down
            self._atr_high = down_val + dev if dev is not None else None
            self._atr_low = down_val - dev if dev is not None else None

        ht = self._up if self._trend == 0 else self._down
        ht = float(ht if ht is not None else 0.0)

        buy_signal = arrow_up is not None and self._trend == 0 and prev_trend == 1
        sell_signal = arrow_down is not None and self._trend == 1 and prev_trend == 0

        # persist previous-bar references
        self._prev_trend = self._trend
        self._prev_up = self._up
        self._prev_down = self._down
        self._prev_bar = candle
        if time_str:
            self._last_time = time_str

        result = HalfTrendResult(
            time=time_str,
            trend=self._trend,
            ht=ht,
            atr_high=self._atr_high,
            atr_low=self._atr_low,
            buy_signal=buy_signal,
            sell_signal=sell_signal,
        )
        self._last_result = result
        return result

    # ------------------------------------------------------------------
    # Introspection (for the empty-DTO and tests)
    # ------------------------------------------------------------------

    @property
    def warmed(self) -> bool:
        return self._warmed


def compute_half_trend_series(
    candles: list,
    amplitude: int = 2,
    channel_deviation: int = 2,
    atr_period: int = 100,
) -> list[HalfTrendResult]:
    """Stateless HalfTrend over a closed-bar history.

    Replays every candle through a fresh detector (reset included) so the
    output equals what the live detector produces after the same history.
    """
    det = HalfTrendDetector(
        amplitude=amplitude,
        channel_deviation=channel_deviation,
        atr_period=atr_period,
    )
    return [det.update(c) for c in candles]
