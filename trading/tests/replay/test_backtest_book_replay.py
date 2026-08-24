"""Backtest tick-level L2 book replay (P1a scalping realism).

A tape carrying ``Depth`` snapshots + a ``BookFillSource`` gives the backtest
real order-book matching: a marketable order sweeps the book from the touch
(VWAP pricing, partial fills on thin books) instead of the guaranteed
next-open fill the simulated source gives. The book state at any fill is the
last snapshot before it — deterministic given the tape (replay parity).

Resting limit orders fill mid-tape: the fill is published as ``OrderFilled``
on the bus and applied by the engine's inbound-fill bridge — the exact path
live broker fills take — so the OMS state matches what a real venue would
have produced.
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
    Quantity,
    Signal,
    Timeframe,
)

from tradex_trading.execution.book_fill_source import BookFillSource
from tradex_trading.execution.fill_sources import SimulatedFillSource
from tradex_trading.replay.backtest import BacktestEngine

INST = Equity.of("NSE", "RELIANCE")
CAPITAL = Decimal("1000000")


def _ts(m: int) -> datetime:
    return datetime(2026, 8, 1, 9, m, tzinfo=UTC)


def _candle(close: str, ts: datetime) -> Candle:
    return Candle(
        instrument=INST,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(value=Decimal("100")),
            high=Price(value=Decimal(close)),
            low=Price(value=Decimal("99")),
            close=Price(value=Decimal(close)),
        ),
        volume=Quantity(value=Decimal("1000")),
        timestamp=ts,
    )


def _depth(bids: list[tuple[str, str]], asks: list[tuple[str, str]], ts: datetime) -> Depth:
    return Depth(
        instrument=INST,
        bids=tuple((Price(value=Decimal(p)), Quantity(value=Decimal(q))) for p, q in bids),
        asks=tuple((Price(value=Decimal(p)), Quantity(value=Decimal(q))) for p, q in asks),
        timestamp=ts,
    )


class _BookTapeStrategy:
    """Emits one BUY signal on the first bar; records depth snapshots it saw."""

    def __init__(self, strength: float) -> None:
        self.strength = strength
        self.strategy_id = "book-tape"
        self.version = "1.0.0"
        self.signals: list[Signal] = []
        self.depth_books: list[Depth] = []

    def on_start(self, context) -> None:
        pass

    def on_bar(self, context, candle) -> Signal | None:
        if not self.signals:
            signal = Signal(
                instrument=INST,
                direction=OrderSide.BUY,
                strength=self.strength,
                reason="book-tape",
                timestamp=candle.timestamp,
            )
            self.signals.append(signal)
            return signal
        return None

    def on_quote(self, context, quote) -> Signal | None:
        return None

    def on_depth(self, context, depth) -> None:
        self.depth_books.append(depth)

    def on_fill(self, context, fill) -> None:
        pass


def _tape() -> list[Candle | Depth]:
    """Bar1 (signal) → book A (5@100.0 + 5@100.5) → Bar2 (open 100)."""
    return [
        _candle("101", _ts(16)),
        _depth([("99.5", "50")], [("100.0", "5"), ("100.5", "5")], _ts(16) + timedelta(seconds=59)),
        _candle("102", _ts(17)),
        _depth([("100.0", "50")], [("102.5", "50")], _ts(17) + timedelta(seconds=59)),
    ]


def test_book_matching_beats_next_open_fill() -> None:
    """8-lot BUY sweeps 5@100.0 + 3@100.5 → VWAP 100.1875, not the 100.0 open."""
    strategy = _BookTapeStrategy(strength=8)
    result = BacktestEngine(
        fill_source=BookFillSource(), initial_capital=CAPITAL,
    ).run(strategy, _tape())

    # 8 * 100.1875 = 801.5 cash out; position 8 @ 100.1875 marked at 102 close.
    assert result.num_trades == 1
    assert result.equity_curve[-1] == float(CAPITAL - Decimal("801.5") + Decimal("816"))


def test_simulated_source_still_fills_at_open() -> None:
    """Control: without a book source the same tape fills at the open (100)."""
    strategy = _BookTapeStrategy(strength=8)
    result = BacktestEngine(
        fill_source=SimulatedFillSource(), initial_capital=CAPITAL,
    ).run(strategy, _tape())

    assert result.num_trades == 1
    assert result.equity_curve[-1] == float(CAPITAL - Decimal("800") + Decimal("816"))


def test_thin_book_produces_partial_fill() -> None:
    """12-lot BUY against 10 lots of asks → 10-lot fill (PARTIALLY_FILLED)."""
    strategy = _BookTapeStrategy(strength=12)
    result = BacktestEngine(
        fill_source=BookFillSource(), initial_capital=CAPITAL,
    ).run(strategy, _tape())

    # 10 @ (500 + 502.5)/10 = 100.25 → 1002.5 cash out; position 10 @ 100.25 @ 102 close.
    assert result.num_trades == 0  # no FILLED order — only a partial
    assert result.equity_curve[-1] == float(CAPITAL - Decimal("1002.5") + Decimal("1020"))


def test_depth_reaches_strategy_on_depth() -> None:
    """Depth events from the tape are published to the strategy's on_depth."""
    strategy = _BookTapeStrategy(strength=8)
    BacktestEngine(
        fill_source=BookFillSource(), initial_capital=CAPITAL,
    ).run(strategy, _tape())

    assert len(strategy.depth_books) == 2
    assert strategy.depth_books[0].best_ask.value == Decimal("100.0")
    assert strategy.depth_books[1].best_ask.value == Decimal("102.5")


def test_resting_limit_fills_through_engine_bridge() -> None:
    """A resting limit fills mid-tape via OrderFilled → engine bridge.

    This is the exact path live broker fills take (ACK order in the cache,
    then OrderFilled applies position + order transition), proving the OMS
    state for a working limit matches what a real venue would produce.
    """
    from tradex_domain.enums import OrderType, TimeInForce
    from tradex_domain.execution import OrderRequest
    from tradex_domain.value_objects import CorrelationId

    from tradex_trading.execution.engine import ExecutionEngine
    from tradex_trading.execution.trading_cache import TradingCache
    from tradex_trading.execution.position_manager import PositionManager
    from tradex_trading.reactive.bus import ReactiveBus

    bus = ReactiveBus()
    cache = TradingCache()
    _ = PositionManager(cache)
    book = BookFillSource()
    book.bind_bus(bus)
    engine = ExecutionEngine(bus, book, cache=cache)

    # Limit BUY at 100.0 rests below the 100.5 ask.
    request = OrderRequest(
        instrument=INST,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Quantity(value=Decimal("10")),
        price=Price(value=Decimal("100.0")),
        time_in_force=TimeInForce.DAY,
        correlation_id=CorrelationId(value="resting-1"),
        reference_timestamp=_ts(16),
    )
    receipt = engine.submit(request)
    assert receipt.status.value == "ACK"
    order_id = receipt.order_id

    # Ask drops to 100.0 → resting order fills via the bridge.
    book.update_depth(
        _depth([("99.0", "50")], [("100.0", "50")], _ts(16) + timedelta(seconds=30))
    )

    # PositionManager stores positions by symbol — the same convention every
    # call site uses (``get_position(instrument.symbol)``).
    position = cache.get_position(INST.symbol)
    assert position is not None
    assert position.quantity.value == Decimal("10")
    assert position.avg_price.value == Decimal("100.0")
    order = cache.get_order(order_id)
    assert order is not None and order.status.value == "FILLED"
    assert order.filled_quantity.value == Decimal("10")
