"""Tick -> Bar aggregator: interval-based (epoch-floored) or range-based windows."""

from __future__ import annotations

from quant.bars import Bar
from quant.brokers.gateway import Tick


class BarAggregator:
    def __init__(self, interval_seconds: int = 60,
                 range_size: float | None = None) -> None:
        self.interval_seconds = interval_seconds
        self.range_size = range_size
        self._open_key: int | None = None
        self._fallback_counter = 0
        self._bar: Bar | None = None

    def _tick_epoch(self, tick: Tick) -> int:
        try:
            return int(tick.time.lstrip("t"))
        except (ValueError, AttributeError):
            self._fallback_counter += 1
            return self._fallback_counter

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
        self._accumulate(tick, window)
        if window != self._open_key:
            closed = self._bar
            self._bar = None
            self._open_key = None
            return closed
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
            self._bar = None
            self._open_key = None
            return closed
        return None

    def _start(self, tick: Tick, window: int | None) -> None:
        self._open_key = window
        self._bar = Bar(time=tick.time, open=tick.price, high=tick.price,
                        low=tick.price, close=tick.price, volume=tick.volume,
                        buy_volume=tick.buy_volume, sell_volume=tick.sell_volume,
                        delta=tick.buy_volume - tick.sell_volume,
                        oi=tick.oi)

    def _accumulate(self, tick: Tick, window: int | None) -> None:
        if self._bar is None:
            self._start(tick, window)
            return
        bar = self._bar
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
        )
