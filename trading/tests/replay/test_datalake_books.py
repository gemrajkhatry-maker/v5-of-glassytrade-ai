"""Datalake-derived books — Depth snapshots rebuilt from OHLCV bars (P1a).

No live depth is needed: each bar's book is anchored on its close with
volume-scaled level quantities. The same bar always yields the same snapshot
(per-bar seed), so full-universe ``BookFillSource`` backtests straight off
the OHLCV datalake are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Depth,
    Equity,
    OrderSide,
    Price,
    Quantity,
    Signal,
    Timeframe,
)

from tradex_trading.execution.book_fill_source import BookFillSource
from tradex_trading.replay.backtest import BacktestEngine
from tradex_trading.replay.datalake_books import (
    DatalakeBookGenerator,
    book_tape_from_candles,
)

INST = Equity.of("NSE", "RELIANCE")
INST2 = Equity.of("NSE", "TCS")


def _candle(
    inst: Equity = INST,
    close: str = "101",
    volume: str = "2000",
    minute: int = 15,
) -> Candle:
    open_p = Decimal("102") if minute > 15 else Decimal("100")
    close_p = Decimal(close)
    return Candle(
        instrument=inst,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(value=open_p),
            high=Price(value=max(open_p, close_p) + Decimal("0.5")),
            low=Price(value=min(open_p, close_p) - Decimal("0.5")),
            close=Price(value=close_p),
        ),
        volume=Quantity(value=Decimal(volume)),
        timestamp=datetime(2026, 8, 1, 9, minute, tzinfo=UTC),
    )


def test_snapshot_is_deterministic_per_bar() -> None:
    candle = _candle()
    gen = DatalakeBookGenerator(seed=7)

    a = gen.snapshot(candle)
    b = gen.snapshot(candle)

    assert a == b
    assert len(a.bids) == 5 and len(a.asks) == 5
    # Book anchored at the close: best ask just above, best bid just below.
    assert a.best_ask is not None and a.best_ask.value > candle.ohlc.close.value
    assert a.best_bid is not None and a.best_bid.value < candle.ohlc.close.value


def test_volume_drives_book_depth() -> None:
    gen = DatalakeBookGenerator(seed=1)

    thin = gen.snapshot(_candle(volume="200"))
    deep = gen.snapshot(_candle(volume="20000"))

    assert deep.asks[0][1].value > thin.asks[0][1].value
    assert deep.bids[0][1].value > thin.bids[0][1].value


def test_books_are_per_instrument() -> None:
    gen = DatalakeBookGenerator(seed=3)

    tape = book_tape_from_candles(
        [_candle(INST), _candle(INST2, close="3200")],
        seed=3,
    )
    books = {type(e).__name__ for e in tape}
    assert books == {"Candle", "Depth"}

    source = BookFillSource()
    for event in tape:
        if isinstance(event, Depth):
            source.update_depth(event)
    assert source.has_book(INST)
    assert source.has_book(INST2)


class _OneShotStrategy:
    """Emits a single BUY on the first bar."""

    def __init__(self) -> None:
        self.strategy_id = "datalake-books"
        self.version = "1.0.0"
        self.signals: list[Signal] = []

    def on_start(self, context) -> None:
        pass

    def on_bar(self, context, candle) -> Signal | None:
        if not self.signals:
            signal = Signal(
                instrument=candle.instrument,
                direction=OrderSide.BUY,
                strength=8,
                reason="datalake-books",
                timestamp=candle.timestamp,
            )
            self.signals.append(signal)
            return signal
        return None

    def on_quote(self, context, quote) -> Signal | None:
        return None

    def on_depth(self, context, depth) -> None:
        pass

    def on_fill(self, context, fill) -> None:
        pass


def test_book_tape_drives_deterministic_backtest() -> None:
    # Bar1 close 101 → bar2 open 102 crosses bar1's book (ask ~101.05).
    candles = [
        _candle(close="101", minute=15),
        _candle(close="103", minute=16),
        _candle(close="101", minute=17),
        _candle(close="103", minute=18),
    ]
    tape = book_tape_from_candles(candles, seed=42)

    kwargs = dict(
        fill_source=BookFillSource(),
        initial_capital=Decimal("1000000"),
    )
    r1 = BacktestEngine(**kwargs).run(_OneShotStrategy(), tape)
    r2 = BacktestEngine(**kwargs).run(_OneShotStrategy(), tape)

    assert r1.num_trades == 1  # the order crossed the volume-derived book
    assert r2.equity_curve == r1.equity_curve
    assert r2.total_fees == r1.total_fees
