"""Tick -> Bar aggregator: interval-based (epoch-floored) or range-based windows."""

from __future__ import annotations

from datetime import datetime

from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.contracts.timezones import IST

# Live ticks carry unix epochs (~1.78e9). Test fixtures use small synthetic
# ids ("t0", "t1", ...) that must pass through unchanged — only floor bar
# times for realistic epochs (>= year 2000) so the live bar time aligns with
# the REST history candle open time (both IST, minute-aligned) and the
# frontend's replace-by-time merge works instead of shadow-appending candles.
_EPOCH_2000 = 946684800


class BarAggregator:
    def __init__(self, interval_seconds: int = 60,
                 range_size: float | None = None) -> None:
        self.interval_seconds = interval_seconds
        self.range_size = range_size
        self._open_key: int | None = None
        self._fallback_counter = 0
        self._bar: Bar | None = None
        self._vwap_num = 0.0
        self._vwap_den = 0.0

    def _tick_epoch(self, tick: Tick) -> int:
        text = str(getattr(tick, "time", "") or "").strip()
        if len(text) >= 2 and text[0] in "tT" and text[1:].isdigit():
            return int(text[1:])
        try:
            epoch = float(text)
            return int(epoch)
        except (TypeError, ValueError):  # silent-except - unparseable tick time falls back to ISO/fallback counter
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=IST)
            return int(parsed.timestamp())
        except (TypeError, ValueError):
            self._fallback_counter += 1
            return self._fallback_counter

    @property
    def current_bar(self) -> Bar | None:
        """The currently forming, unclosed candle updated on every tick."""
        return self._bar

    def _window(self, epoch: int) -> int:
        return epoch // self.interval_seconds if self.interval_seconds else epoch

    def add_tick(self, tick: Tick) -> Bar | None:
        if self.range_size is not None:
            return self._add_range(tick)
        return self._add_interval(tick)

    def _add_interval(self, tick: Tick) -> Bar | None:
        window = self._window(self._tick_epoch(tick))
        if self._bar is None:
            self._start(tick, window)
            return None
        if window < self._open_key:
            # Late data must not mutate an already-open exchange window.
            return None
        if window != self._open_key:
            closed = self._bar
            self._start(tick, window)
            return closed
        self._accumulate(tick, window)
        return None

    def _add_range(self, tick: Tick) -> Bar | None:
        if self._bar is None:
            self._start(tick, None)
            return None
        self._accumulate(tick, self._open_key)
        assert self._bar is not None
        spread = max(self._bar.high, tick.price) - min(self._bar.low, tick.price)
        if spread >= self.range_size:
            closed = self._bar
            self._start(tick, None)
            return closed
        return None

    def _bar_time(self, tick: Tick, window: int | None) -> str:
        """Floor live epochs to the window start; keep synthetic ids as-is."""
        if (self.interval_seconds and window is not None
                and self._tick_epoch(tick) >= _EPOCH_2000):
            return str(window * self.interval_seconds)
        return tick.time

    def _start(self, tick: Tick, window: int | None) -> None:
        self._open_key = window
        self._vwap_num = tick.price * tick.volume
        self._vwap_den = tick.volume
        self._bar = Bar(time=self._bar_time(tick, window), open=tick.price,
                        high=tick.price, low=tick.price, close=tick.price,
                        volume=tick.volume,
                        buy_volume=tick.buy_volume, sell_volume=tick.sell_volume,
                        delta=tick.buy_volume - tick.sell_volume,
                        oi=tick.oi,
                        vwap=self._vwap() if self._vwap_den > 0 else tick.price)

    def _accumulate(self, tick: Tick, window: int | None) -> None:
        if self._bar is None:
            self._start(tick, window)
            return
        bar = self._bar
        self._vwap_num += tick.price * tick.volume
        self._vwap_den += tick.volume
        self._bar = Bar(
            time=bar.time, open=bar.open,
            high=max(bar.high, tick.price),
            low=min(bar.low, tick.price),
            close=tick.price,
            volume=bar.volume + tick.volume,
            buy_volume=bar.buy_volume + tick.buy_volume,
            sell_volume=bar.sell_volume + tick.sell_volume,
            delta=(bar.buy_volume + tick.buy_volume)
                  - (bar.sell_volume + tick.sell_volume),
            oi=tick.oi,
            vwap=self._vwap() if self._vwap_den > 0 else tick.price,
        )

    def _vwap(self) -> float:
        return self._vwap_num / self._vwap_den
