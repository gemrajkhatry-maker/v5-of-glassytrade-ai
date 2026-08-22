"""L2 book-matching determinism under a high-frequency synthetic tape (P1a).

A 12-bar tick-level tape (60 ticks/bar, 5 depth levels per side) drives a
``BookFillSource`` backtest twice from the same seed. The book state at every
fill is a pure function of the tape, so two runs must reproduce identical
fills, fees, rejected counts, and equity to the rupee — the replay-parity
guarantee for order-book matching.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Depth,
    Equity,
    OrderSide,
    Price,
    Quote,
    Quantity,
    Signal,
    TestClock,
    Timeframe,
)

from tradex_trading.execution.book_fill_source import BookFillSource
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.replay.backtest import BacktestEngine
from tradex_trading.replay.synthetic_ticks import SyntheticTickGenerator

INST = Equity.of("NSE", "RELIANCE")


def _candles(n: int = 12) -> list[Candle]:
    """Alternating 101/103 closes with 102 opens: BUY and SELL signals both
    cross the previous bar's book (open 102 >= 101.05 for BUYs, <= 102.95 for
    SELLs), so every deferred order actually exercises matching."""
    candles: list[Candle] = []
    for i in range(n):
        close = Decimal("101" if i % 2 == 0 else "103")
        open_p = Decimal("102")
        candles.append(
            Candle(
                instrument=INST,
                timeframe=Timeframe.M1,
                ohlc=OHLC(
                    open=Price(value=open_p),
                    high=Price(value=max(open_p, close) + Decimal("0.5")),
                    low=Price(value=min(open_p, close) - Decimal("0.5")),
                    close=Price(value=close),
                ),
                volume=Quantity(value=Decimal("3000")),
                timestamp=datetime(2026, 8, 1, 9, 15 + i, tzinfo=UTC),
            )
        )
    return candles


class _AlternatingStrategy:
    """BUY on odd bars, SELL on even bars, strength cycling 5..15."""

    def __init__(self) -> None:
        self.strategy_id = "alternating"
        self.version = "1.0.0"
        self.signals: list[Signal] = []

    def on_start(self, context) -> None:
        pass

    def on_bar(self, context, candle) -> Signal | None:
        n = len(self.signals)
        direction = OrderSide.BUY if n % 2 == 0 else OrderSide.SELL
        strength = float(5 + (n % 11))
        signal = Signal(
            instrument=INST,
            direction=direction,
            strength=strength,
            reason=f"bar-{n + 1}-{direction.value}",
            timestamp=candle.timestamp,
        )
        self.signals.append(signal)
        return signal

    def on_quote(self, context, quote) -> Signal | None:
        return None

    def on_depth(self, context, depth) -> None:
        pass

    def on_fill(self, context, fill) -> None:
        pass


def _tape() -> list[Candle | Depth]:
    """High-frequency tape: candles + per-tick quotes + per-bar depth snapshots."""
    candles = _candles()
    bus = ReactiveBus()
    collected: list[object] = []
    bus.of_type(Depth).subscribe(lambda d: collected.append(d))
    bus.of_type(Quote).subscribe(lambda q: collected.append(q))
    generator = SyntheticTickGenerator(
        bus, seed=42, method="bridge", depth_levels=5, ticks_per_bar=60,
    )
    for candle in candles:
        generator.feed_bar(candle)
    return candles + collected  # type: ignore[list-item]


def test_identical_runs_on_high_frequency_l2_tape() -> None:
    tape = _tape()
    strategy1 = _AlternatingStrategy()
    strategy2 = _AlternatingStrategy()
    kwargs = dict(
        fill_source=BookFillSource(),
        clock=TestClock(),
        initial_capital=Decimal("1000000"),
    )
    result1 = BacktestEngine(**kwargs).run(strategy1, tape)
    result2 = BacktestEngine(**kwargs).run(strategy2, tape)

    # Sanity: the tape genuinely exercised L2 matching.
    assert result1.num_trades > 0

    # Determinism: identical outcomes to the rupee.
    assert result2.num_trades == result1.num_trades
    assert result2.num_rejected == result1.num_rejected
    assert result2.total_fees == result1.total_fees
    assert result2.equity_curve == result1.equity_curve
    assert [s.reason for s in result2.trades] == [s.reason for s in result1.trades]
