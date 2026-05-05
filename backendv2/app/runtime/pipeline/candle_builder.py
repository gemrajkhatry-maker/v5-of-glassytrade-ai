"""CandlePipeline — OHLC candle building from normalized ticks.

Owns: active candle per symbol per timeframe.
Hot path: compare price against H/L, increment volume. No allocation.
"""

from __future__ import annotations

import logging
from typing import Any
from typing import Optional

from app.runtime.pipeline.events import NormalizedTick, Candle, CandleTimeframe

logger = logging.getLogger(__name__)

# Nanoseconds per timeframe
NS_PER_MINUTE = 60_000_000_000
NS_PER_HOUR = 3_600_000_000_000
NS_PER_DAY = 86_400_000_000_000

CANDLE_TIMEFRAMES_NS: dict[CandleTimeframe, int] = {
    CandleTimeframe.M1: NS_PER_MINUTE,
    CandleTimeframe.M5: 5 * NS_PER_MINUTE,
    CandleTimeframe.M15: 15 * NS_PER_MINUTE,
    CandleTimeframe.H1: NS_PER_HOUR,
    CandleTimeframe.D1: NS_PER_DAY,
}


class _CandleBuilder:
    """Mutable candle builder. Updated in-place per tick."""

    def __init__(self, symbol: str, timeframe: CandleTimeframe, tick: NormalizedTick):
        period_start = _period_start(tick.timestamp, CANDLE_TIMEFRAMES_NS[timeframe])
        self.symbol = symbol
        self.timeframe = timeframe
        self.open = tick.price
        self.high = tick.price
        self.low = tick.price
        self.close = tick.price
        self.volume = tick.volume
        self.period_start = period_start
        self.tick_count = 1
        self.buy_volume = tick.bid_volume
        self.sell_volume = tick.ask_volume

    def update(self, tick: NormalizedTick) -> None:
        if tick.price > self.high:
            self.high = tick.price
        if tick.price < self.low:
            self.low = tick.price
        self.close = tick.price
        self.volume += tick.volume
        self.tick_count += 1
        self.buy_volume += tick.bid_volume
        self.sell_volume += tick.ask_volume

    def to_candle(self) -> Candle:
        return Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            timestamp=self.period_start + CANDLE_TIMEFRAMES_NS[self.timeframe],
            tick_count=self.tick_count,
            buy_volume=self.buy_volume,
            sell_volume=self.sell_volume,
            complete=True,
        )


def _period_start(timestamp_ns: int, period_ns: int) -> int:
    """Round timestamp down to period boundary."""
    return (timestamp_ns // period_ns) * period_ns


class CandlePipeline:
    """Builds OHLC candles from ticks across multiple timeframes.

    Produces completed candle events when a new period starts.
    """

    def __init__(self):
        # Active candles: (symbol, timeframe) -> CandleBuilder
        self._active: dict[tuple[str, CandleTimeframe], _CandleBuilder] = {}
        self._timeframes = list(CANDLE_TIMEFRAMES_NS.keys())

    def process(self, tick: NormalizedTick) -> list[Candle]:
        """Process one tick. Returns completed candles (if any)."""
        completed: list[Candle] = []

        for tf in self._timeframes:
            key = (tick.symbol, tf)
            period_ns = CANDLE_TIMEFRAMES_NS[tf]
            current_period = _period_start(tick.timestamp, period_ns)

            builder = self._active.get(key)

            if builder is None:
                # First tick for this symbol/timeframe
                self._active[key] = _CandleBuilder(tick.symbol, tf, tick)
            elif current_period != builder.period_start:
                # Period boundary crossed — emit completed candle
                completed.append(builder.to_candle())
                self._active[key] = _CandleBuilder(tick.symbol, tf, tick)
            else:
                # Same period — update in place
                builder.update(tick)

        return completed

    def get_active(self, symbol: str) -> Optional[Candle]:
        """Get active 1-minute candle for symbol (for testing)."""
        key = (symbol, CandleTimeframe.M1)
        builder = self._active.get(key)
        if builder is None:
            return None
        return Candle(
            symbol=builder.symbol,
            timeframe=builder.timeframe,
            open=builder.open,
            high=builder.high,
            low=builder.low,
            close=builder.close,
            volume=builder.volume,
            timestamp=builder.period_start + CANDLE_TIMEFRAMES_NS[builder.timeframe],
            tick_count=builder.tick_count,
            buy_volume=builder.buy_volume,
            sell_volume=builder.sell_volume,
            complete=False,
        )

    def snapshot(self) -> dict[str, Any]:
        active_payload: list[dict[str, Any]] = []
        for (symbol, timeframe), builder in self._active.items():
            active_payload.append({
                "symbol": symbol,
                "timeframe": timeframe.value,
                "open": builder.open,
                "high": builder.high,
                "low": builder.low,
                "close": builder.close,
                "volume": builder.volume,
                "period_start": builder.period_start,
                "tick_count": builder.tick_count,
                "buy_volume": builder.buy_volume,
                "sell_volume": builder.sell_volume,
            })
        return {
            "timeframes": [tf.value for tf in self._timeframes],
            "active": active_payload,
        }

    def restore(self, payload: dict[str, Any]) -> None:
        self._active = {}
        saved_timeframes = payload.get("timeframes")
        if isinstance(saved_timeframes, list):
            self._timeframes = []
            valid_timeframes = {t.value for t in CandleTimeframe}
            for raw_timeframe in saved_timeframes:
                if isinstance(raw_timeframe, CandleTimeframe):
                    self._timeframes.append(raw_timeframe)
                elif raw_timeframe in valid_timeframes:
                    self._timeframes.append(CandleTimeframe(raw_timeframe))
            if not self._timeframes:
                self._timeframes = list(CANDLE_TIMEFRAMES_NS.keys())
        else:
            self._timeframes = list(CANDLE_TIMEFRAMES_NS.keys())

        active_payload = payload.get("active", [])
        if isinstance(active_payload, list):
            for item in active_payload:
                if not isinstance(item, dict):
                    continue
                tf_value = item.get("timeframe")
                try:
                    timeframe = CandleTimeframe(tf_value) if tf_value is not None else CandleTimeframe.M1
                except ValueError:
                    timeframe = CandleTimeframe.M1
                symbol = str(item.get("symbol", ""))
                builder = _CandleBuilder.__new__(_CandleBuilder)
                builder.symbol = symbol
                builder.timeframe = timeframe
                builder.open = float(item.get("open", 0.0))
                builder.high = float(item.get("high", 0.0))
                builder.low = float(item.get("low", 0.0))
                builder.close = float(item.get("close", 0.0))
                builder.volume = float(item.get("volume", 0.0))
                builder.period_start = int(item.get("period_start", 0))
                builder.tick_count = int(item.get("tick_count", 1))
                builder.buy_volume = float(item.get("buy_volume", 0.0))
                builder.sell_volume = float(item.get("sell_volume", 0.0))
                self._active[(symbol, timeframe)] = builder

    def build_candles(self, ticks: list[NormalizedTick]) -> dict[str, list[Candle]]:
        """Build all completed candles from a list of ticks (for backtest)."""
        result: dict[str, list[Candle]] = {}
        for tick in ticks:
            completed = self.process(tick)
            for c in completed:
                if c.symbol not in result:
                    result[c.symbol] = []
                result[c.symbol].append(c)
        return result

    def warmup(self) -> None:
        self._active = {}
        logger.info("CandlePipeline warmed up")

    def teardown(self) -> None:
        count = len(self._active)
        self._active = {}
        logger.info("CandlePipeline teardown: %d active candles flushed", count)

    def reset(self) -> None:
        self._active = {}