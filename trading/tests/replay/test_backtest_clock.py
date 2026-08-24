"""Backtest clock wiring (P0-1).

The backtest advances its ``TestClock`` to each event's timestamp as the tape
streams, and the strategy engine injects that clock into ``StrategyContext``.
A strategy reading ``context.clock.now()`` therefore sees the *simulated*
instant — identical across replay runs — never wall time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Equity,
    Price,
    Quantity,
    Signal,
    TestClock,
    Timeframe,
)

from tradex_trading.replay.backtest import BacktestEngine


def _ts(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 1, h, m, tzinfo=UTC)


def _eq() -> Equity:
    return Equity.of("NSE", "RELIANCE")


def _candle(close: Decimal, ts: datetime) -> Candle:
    return Candle(
        instrument=_eq(),
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(value=close),
            high=Price(value=close + Decimal("1")),
            low=Price(value=close - Decimal("1")),
            close=Price(value=close),
        ),
        volume=Quantity(value=Decimal("1000")),
        timestamp=ts,
    )


class _ClockObservingStrategy:
    """Records the clock time seen on each bar (and never emits signals)."""

    def __init__(self) -> None:
        self.seen: list[datetime] = []
        self.strategy_id = "clock-observer"
        self.version = "1.0.0"
        self.signals: list[Signal] = []

    def on_start(self, context) -> None:
        pass

    def on_bar(self, context, candle) -> Signal | None:
        clock_now = context.clock.now() if context.clock is not None else None
        self.seen.append(clock_now)
        return None

    def on_quote(self, context, quote) -> Signal | None:
        return None

    def on_depth(self, context, depth) -> Signal | None:
        return None

    def on_fill(self, context, fill) -> None:
        pass

    def on_stop(self, context) -> None:
        pass


def test_backtest_advances_clock_to_each_bar() -> None:
    candles = [
        _candle(Decimal("100"), _ts(9, 15)),
        _candle(Decimal("101"), _ts(9, 16)),
        _candle(Decimal("102"), _ts(9, 17)),
    ]
    clock = TestClock(start=_ts(9, 14))
    strategy = _ClockObservingStrategy()

    result = BacktestEngine(clock=clock).run(strategy, list(candles))

    # The clock advanced to every bar's instant in stream order.
    assert strategy.seen == [c.timestamp for c in candles]
    # The engine's clock ended at the final bar's instant.
    assert clock.now() == candles[-1].timestamp
    # Nothing traded (the observer emits no signals).
    assert result.num_trades == 0


def test_backtest_clock_is_deterministic_across_runs() -> None:
    """Re-running the same tape on fresh clocks sees identical instants."""
    candles = [
        _candle(Decimal("100"), _ts(9, 15)),
        _candle(Decimal("101"), _ts(9, 16)),
        _candle(Decimal("102"), _ts(9, 17)),
    ]

    def _run() -> list[datetime]:
        clock = TestClock(start=_ts(9, 0))
        strategy = _ClockObservingStrategy()
        BacktestEngine(clock=clock).run(strategy, list(candles))
        return strategy.seen

    assert _run() == _run() == [c.timestamp for c in candles]


def test_default_backtest_clock_is_advanceable_testclock() -> None:
    """No clock passed → the engine uses a TestClock it drives itself."""
    candles = [_candle(Decimal("100"), _ts(9, 15))]
    strategy = _ClockObservingStrategy()
    engine = BacktestEngine()
    engine.run(strategy, list(candles))
    assert strategy.seen == [_ts(9, 15)]
    # The engine's own clock now reflects the simulated instant.
    assert engine._clock.now() == _ts(9, 15)
