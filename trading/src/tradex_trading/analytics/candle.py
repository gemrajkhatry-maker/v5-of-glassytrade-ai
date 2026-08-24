"""Orderflow candle builder — aggregate a Quote stream into enriched candles.

Mirrors the OrderFlow reference's ``CandleBuilder``, but consumes TradeX
``Quote`` events (LTP + volume + depth) rather than raw exchange ticks. The
aggressor side is inferred with ``classify_aggressor`` (LTP vs mid), the same
convention the existing ``Footprint`` accumulator already uses.

Note on volume semantics: each ``Quote.volume`` is attributed to the inferred
aggressor side per event — consistent with ``Footprint`` / ``cvd_from_quotes``.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain.enums import Timeframe
from tradex_domain.market import OHLC, Quote
from tradex_domain.value_objects import Quantity

from tradex_trading.analytics.orderflow import classify_aggressor, round_price
from tradex_trading.analytics.orderflow_types import FootprintLevel, OrderflowCandle

_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
}


def _bucket_start(timestamp: datetime, timeframe: Timeframe) -> datetime:
    """Floor *timestamp* to the timeframe boundary (UTC)."""
    if timeframe in _SECONDS:
        step = _SECONDS[timeframe]
        epoch = calendar.timegm(timestamp.utctimetuple())
        return datetime.fromtimestamp((epoch // step) * step, tz=UTC)
    if timeframe is Timeframe.D1:
        return datetime(timestamp.year, timestamp.month, timestamp.day, tzinfo=UTC)
    if timeframe is Timeframe.W1:
        day = timestamp.date() - timedelta(days=timestamp.weekday())
        return datetime(day.year, day.month, day.day, tzinfo=UTC)
    # Unknown timeframe — treat each quote as its own bucket start (never block).
    return timestamp


class OrderflowCandleBuilder:
    """Builds time-based ``OrderflowCandle`` bars from a ``Quote`` stream.

    Each bar carries full footprint data (bid/ask volume per price level) plus
    buy/sell volume totals and tick count, so the delta/footprint/volume-profile
    engines can consume it directly.
    """

    def __init__(
        self,
        timeframe: Timeframe = Timeframe.M1,
        *,
        tick_size: float = 0.05,
        max_history: int = 5000,
        on_close: Callable[[OrderflowCandle], None] | None = None,
    ) -> None:
        self.timeframe = timeframe
        self.tick_size = tick_size
        self._max_history = max_history
        self.on_close = on_close
        self._current: OrderflowCandle | None = None
        self._history: list[OrderflowCandle] = []

    @staticmethod
    def _round_price(price: float, tick_size: float) -> float:
        return round_price(price, tick_size)

    def process(self, quote: Quote) -> OrderflowCandle | None:
        """Feed a quote; return the closed candle when the bar boundary rolls."""
        start = _bucket_start(quote.timestamp, self.timeframe)
        closed: OrderflowCandle | None = None

        if self._current is not None and start > self._current.timestamp:
            closed = self._current
            if self.on_close is not None:
                self.on_close(closed)
            self._history.append(closed)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
            self._current = None

        ltp = float(quote.ltp.value)
        bid = float(quote.bid.value) if quote.bid is not None else ltp
        ask = float(quote.ask.value) if quote.ask is not None else ltp
        vol = float(quote.volume.value) if quote.volume is not None else 0.0

        if self._current is None:
            self._current = OrderflowCandle(
                instrument=quote.instrument,
                timeframe=self.timeframe,
                ohlc=OHLC(open=quote.ltp, high=quote.ltp, low=quote.ltp, close=quote.ltp),
                volume=Quantity(Decimal(0)),
                timestamp=start,
            )

        c = self._current
        assert c is not None
        # OHLC update (Decimal, matching domain Candle semantics).
        o = c.ohlc
        new_ohlc = OHLC(
            open=o.open,
            high=o.high if o.high.value > quote.ltp.value else quote.ltp,
            low=o.low if o.low.value < quote.ltp.value else quote.ltp,
            close=quote.ltp,
        )
        volume = Quantity(c.volume.value + (quote.volume.value if quote.volume else Decimal(0)))

        buy_vol = c.buy_volume
        sell_vol = c.sell_volume
        tick_count = c.tick_count + (1 if quote.volume is not None else 0)

        direction = classify_aggressor(ltp=ltp, bid=bid, ask=ask)
        if direction > 0:
            buy_vol += vol
        elif direction < 0:
            sell_vol += vol

        fp = dict(c.footprint)
        if vol > 0.0 and direction != 0:
            price = self._round_price(ltp, self.tick_size)
            level = fp.get(price, FootprintLevel(price=price))
            if direction > 0:
                level = FootprintLevel(
                    price=price,
                    bid_volume=level.bid_volume,
                    ask_volume=level.ask_volume + vol,
                )
            else:
                level = FootprintLevel(
                    price=price,
                    bid_volume=level.bid_volume + vol,
                    ask_volume=level.ask_volume,
                )
            fp[price] = level

        self._current = OrderflowCandle(
            instrument=c.instrument,
            timeframe=c.timeframe,
            ohlc=new_ohlc,
            volume=volume,
            timestamp=c.timestamp,
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            tick_count=tick_count,
            footprint=fp,
        )
        return closed

    @property
    def current(self) -> OrderflowCandle | None:
        return self._current

    @property
    def history(self) -> list[OrderflowCandle]:
        return self._history

    def get_recent(self, n: int) -> list[OrderflowCandle]:
        return self._history[-n:]

    def close_current(self) -> OrderflowCandle | None:
        """Force-close the in-progress candle (e.g. end of session)."""
        if self._current is None:
            return None
        closed = self._current
        if self.on_close is not None:
            self.on_close(closed)
        self._history.append(closed)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        self._current = None
        return closed


__all__ = ["OrderflowCandleBuilder"]
