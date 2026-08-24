"""End-to-end AMT strategy test.

Proves the full v4 pipeline for the AMT extension:
Quote events -> OrderflowCandleBuilder -> AMTKernel -> Triple-A signal
-> ReactiveStrategyEngine (next_open) -> ExecutionEngine -> Fill -> PositionManager.

Same code path live/paper/replay uses (BacktestEngine is a bus driver).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Equity,
    OrderSide,
    Price,
    Quantity,
    Quote,
    Timeframe,
)
from tradex_domain.enums import OrderStatus, OrderType
from tradex_domain.events import PlaceOrderCommand
from tradex_domain.execution import OrderRequest

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.execution.fill_sources import SimulatedFillSource
from tradex_trading.execution.trading_cache import TradingCache
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.replay.backtest import BacktestEngine
from tradex_trading.strategy.core.engine import ReactiveStrategyEngine
from tradex_trading.strategy.extensions.amt.strategy import AMTStrategy

INSTRUMENT = Equity.of("NSE", "RELIANCE")
BASE = datetime(2026, 8, 1, 9, 15, tzinfo=UTC)


def _quote(minute: int, *, ltp: str, bid: str, ask: str, volume: str = "50") -> Quote:
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(Decimal(ltp)),
        bid=Price(Decimal(bid)),
        ask=Price(Decimal(ask)),
        volume=Quantity(Decimal(volume)),
        timestamp=BASE + timedelta(minutes=minute),
    )


def _candle(minute: int, close: str) -> Candle:
    price = Decimal(close)
    return Candle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(price - Decimal("0.5")),
            high=Price(price + Decimal("0.5")),
            low=Price(price - Decimal("0.5")),
            close=Price(price),
        ),
        volume=Quantity(Decimal("100")),
        timestamp=BASE + timedelta(minutes=minute),
    )


def _triple_a_tape() -> list:
    """Quote tape that closes a BUY Triple-A signal, then bars to fill it.

    - 20 baseline minutes: wide bars (99.5-100.5), 100 volume, delta 0.
    - minute 20: absorption spike — compressed range, 5x volume, buyer
      aggressive, closing INSIDE the value area (so only the Triple-A setup
      fires, not the secondary VA_FADE).
    - minute 21: normal bar near POC -> accumulation.
    - minute 22: breakout close above VWAP+1sigma -> AGGRESSION/LONG signal.
    - minute 23: quote that closes the breakout candle (signal fires here).
    - minutes 24-25: candles that fill the deferred next_open order.
    """
    events: list = []
    for minute in range(20):
        events.append(_quote(minute, ltp="99.5", bid="99.5", ask="100.5"))
        events.append(_quote(minute, ltp="100.5", bid="99.5", ask="100.5"))
    events.append(_quote(20, ltp="100.3", bid="100.0", ask="100.3", volume="500"))
    events.append(_quote(21, ltp="99.5", bid="99.5", ask="100.5"))
    events.append(_quote(21, ltp="100.5", bid="99.5", ask="100.5"))
    events.append(_quote(22, ltp="101.5", bid="101.0", ask="101.5", volume="100"))
    events.append(_quote(23, ltp="101.0", bid="100.5", ask="101.5"))
    events.append(_candle(24, "101.5"))
    events.append(_candle(25, "102.0"))
    return events


def test_amt_signal_reaches_execution_and_fills() -> None:
    engine = BacktestEngine()
    strategy = AMTStrategy("amt-e2e", INSTRUMENT)
    result = engine.run(strategy, _triple_a_tape())

    # The strategy emitted exactly one Triple-A signal and it was a LONG.
    triple_a = [s for s in result.trades if s.reason == "TRIPLE_A"]
    assert len(triple_a) == 1
    assert triple_a[0].direction == OrderSide.BUY

    # The signal produced a real fill through ExecutionEngine.
    assert result.num_trades == 1
    assert result.equity_curve[-1] > result.equity_curve[0]


def test_amt_end_to_end_is_deterministic() -> None:
    def run():
        engine = BacktestEngine()
        strategy = AMTStrategy("amt-e2e", INSTRUMENT)
        return engine.run(strategy, _triple_a_tape())

    first = run()
    second = run()
    assert first.num_trades == second.num_trades
    assert [s.reason for s in first.trades] == [s.reason for s in second.trades]


def test_amt_order_request_and_fill_are_verified() -> None:
    """Capture the actual PlaceOrderCommand and filled order from the pipeline."""
    bus = ReactiveBus()
    cache = TradingCache()
    ExecutionEngine(bus, SimulatedFillSource(), cache=cache)
    strategy_engine = ReactiveStrategyEngine(bus, fill_reference="next_open")
    strategy = AMTStrategy("amt-order", INSTRUMENT)
    strategy_engine.register(strategy)

    captured: list[OrderRequest] = []
    bus.of_type(PlaceOrderCommand).subscribe(
        lambda command: captured.append(command.request)
    )

    for event in _triple_a_tape():
        bus.publish(event)

    assert len(captured) == 1
    request = captured[0]
    assert request.instrument == INSTRUMENT
    assert request.side == OrderSide.BUY
    assert request.order_type == OrderType.MARKET
    assert request.quantity.value == Decimal("1")  # SignalStrengthSizer: abs(strength)
    assert request.price.value == Decimal("101.0")  # next candle's open
    assert "amt-order" in request.tag

    filled = [o for o in cache.all_orders() if o.status == OrderStatus.FILLED]
    assert len(filled) == 1
    assert filled[0].side == OrderSide.BUY
    assert filled[0].quantity.value == request.quantity.value

    # The signal's structural plan (stop/target) is stamped for the exit layer.
    assert len(strategy.signals) == 1
    meta = strategy.signals[0].metadata
    assert (
        Decimal(meta["stop_loss"])
        < Decimal(meta["entry"])
        < Decimal(meta["take_profit"])
    )
    strategy_engine.dispose_all()
