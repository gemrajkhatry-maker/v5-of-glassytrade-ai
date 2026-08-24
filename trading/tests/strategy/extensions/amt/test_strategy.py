from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Depth,
    Equity,
    Fill,
    OrderId,
    OrderSide,
    Price,
    Quantity,
    Quote,
    Timeframe,
)

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.strategy.core.engine import ReactiveStrategyEngine
from tradex_trading.strategy.core.protocols import Strategy
from tradex_trading.strategy.extensions.amt.model import AMTStrategyConfig
from tradex_trading.strategy.extensions.amt.strategy import AMTStrategy

INSTRUMENT = Equity.of("NSE", "RELIANCE")


def _candle(i: int, close: str, volume: str = "100") -> Candle:
    price = Decimal(close)
    return Candle(
        instrument=INSTRUMENT, timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(price),
            high=Price(price + 1),
            low=Price(price - 1),
            close=Price(price),
        ),
        volume=Quantity(Decimal(volume)),
        timestamp=datetime(2026, 8, 1, 9, 15 + i, tzinfo=UTC),
    )


def test_amt_strategy_is_explicit_strategy_protocol_instance() -> None:
    strategy = AMTStrategy("amt-test", INSTRUMENT)

    assert isinstance(strategy, Strategy)
    assert strategy.strategy_id == "amt-test"
    assert strategy.version.startswith("1.")


def test_amt_strategy_consumes_quotes_through_existing_reactive_engine() -> None:
    bus = ReactiveBus()
    engine = ReactiveStrategyEngine(bus, fill_reference="signal_close")
    strategy = AMTStrategy("amt-quotes", INSTRUMENT)
    engine.register(strategy)

    first = Quote(
        instrument=INSTRUMENT,
        ltp=Price(Decimal("100.75")),
        bid=Price(Decimal("100")),
        ask=Price(Decimal("101")),
        volume=Quantity(Decimal("100")),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
    )
    second = Quote(
        instrument=INSTRUMENT,
        ltp=Price(Decimal("101.5")),
        bid=Price(Decimal("101")),
        ask=Price(Decimal("102")),
        volume=Quantity(Decimal("100")),
        timestamp=datetime(2026, 8, 1, 9, 16, tzinfo=UTC),
    )
    bus.publish(first)
    bus.publish(second)

    assert len(strategy.snapshots) == 1
    assert strategy.snapshots[0].delta == Decimal("100")
    engine.dispose_all()


def test_amt_strategy_is_driven_by_existing_reactive_engine() -> None:
    bus = ReactiveBus()
    engine = ReactiveStrategyEngine(bus, fill_reference="signal_close")
    strategy = AMTStrategy("amt-test", INSTRUMENT)
    engine.register(strategy)

    for i in range(8):
        bus.publish(_candle(i, str(100 + (i % 2))))

    assert strategy.snapshots
    assert all(snapshot.instrument == INSTRUMENT for snapshot in strategy.snapshots)
    engine.dispose_all()


def test_amt_strategy_tracks_l2_depth_through_reactive_engine() -> None:
    bus = ReactiveBus()
    engine = ReactiveStrategyEngine(bus, fill_reference="signal_close")
    strategy = AMTStrategy("amt-depth", INSTRUMENT)
    engine.register(strategy)

    depth = Depth(
        instrument=INSTRUMENT,
        bids=((Price(Decimal("100")), Quantity(Decimal("500"))),),
        asks=((Price(Decimal("101")), Quantity(Decimal("50"))),),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
    )
    bus.publish(depth)
    bus.publish(_candle(0, "100"))

    snapshot = strategy.snapshots[-1]
    assert snapshot.book_polr == "up"
    assert snapshot.book_imbalance > 0
    engine.dispose_all()


def _fill(i: int, side: OrderSide, price: str, qty: str = "1") -> Fill:
    return Fill(
        order_id=OrderId(value=f"o{i}"),
        instrument=INSTRUMENT,
        side=side,
        quantity=Quantity(Decimal(qty)),
        price=Price(Decimal(price)),
        timestamp=datetime(2026, 8, 1, 9, 15 + i, tzinfo=UTC),
    )


def test_fills_drive_position_state_and_loss_streak() -> None:
    bus = ReactiveBus()
    engine = ReactiveStrategyEngine(bus)
    strategy = AMTStrategy("amt-fills", INSTRUMENT)
    engine.register(strategy)

    bus.publish(_fill(0, OrderSide.BUY, "100"))
    assert strategy.position_direction == "LONG"
    assert strategy.consecutive_losses == 0

    bus.publish(_fill(1, OrderSide.SELL, "99"))  # closing fill at a loss
    assert strategy.position_direction is None
    assert strategy.consecutive_losses == 1
    engine.dispose_all()


def test_loss_cushion_shrinks_risk_after_consecutive_losses() -> None:
    strategy = AMTStrategy(
        "amt-loss",
        INSTRUMENT,
        AMTStrategyConfig(loss_streak_threshold=2, risk_shrink_factor=Decimal("0.5")),
    )

    assert strategy.risk_multiplier == Decimal("1")
    strategy.record_trade_outcome(Decimal("-10"))
    strategy.record_trade_outcome(Decimal("-4"))
    assert strategy.risk_multiplier == Decimal("0.5")

    strategy.record_trade_outcome(Decimal("8"))  # win resets the streak
    assert strategy.risk_multiplier == Decimal("1")


def _high_aggression_tape() -> list:
    """Quote tape whose breakout bar carries 5x volume (aggression >= 3)."""
    events: list = []
    for minute in range(20):
        events.append(Quote(
            instrument=INSTRUMENT, ltp=Price(Decimal("99.5")),
            bid=Price(Decimal("99.5")), ask=Price(Decimal("100.5")),
            volume=Quantity(Decimal("50")),
            timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
            + timedelta(minutes=minute),
        ))
        events.append(Quote(
            instrument=INSTRUMENT, ltp=Price(Decimal("100.5")),
            bid=Price(Decimal("99.5")), ask=Price(Decimal("100.5")),
            volume=Quantity(Decimal("50")),
            timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
            + timedelta(minutes=minute),
        ))
    events.append(Quote(
        instrument=INSTRUMENT, ltp=Price(Decimal("100.3")),
        bid=Price(Decimal("100.0")), ask=Price(Decimal("100.3")),
        volume=Quantity(Decimal("500")),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
        + timedelta(minutes=20),
    ))
    events.append(Quote(
        instrument=INSTRUMENT, ltp=Price(Decimal("100.5")),
        bid=Price(Decimal("99.5")), ask=Price(Decimal("100.5")),
        volume=Quantity(Decimal("50")),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
        + timedelta(minutes=21),
    ))
    events.append(Quote(
        instrument=INSTRUMENT, ltp=Price(Decimal("101.5")),
        bid=Price(Decimal("101.0")), ask=Price(Decimal("101.5")),
        volume=Quantity(Decimal("500")),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
        + timedelta(minutes=22),
    ))
    events.append(Quote(
        instrument=INSTRUMENT, ltp=Price(Decimal("101.0")),
        bid=Price(Decimal("100.5")), ask=Price(Decimal("101.5")),
        volume=Quantity(Decimal("50")),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
        + timedelta(minutes=23),
    ))
    return events


def test_strategy_pyramids_into_open_position_on_strong_aggression() -> None:
    bus = ReactiveBus()
    engine = ReactiveStrategyEngine(bus)
    strategy = AMTStrategy("amt-pyr", INSTRUMENT)
    engine.register(strategy)

    bus.publish(_fill(0, OrderSide.BUY, "100"))  # open a LONG position
    for event in _high_aggression_tape():
        bus.publish(event)

    pyramids = [s for s in strategy.signals if s.metadata.get("setup") == "PYRAMID"]
    assert pyramids, "expected a pyramiding signal into the open LONG position"
    assert pyramids[0].direction == OrderSide.BUY
    assert strategy.snapshots[-1].aggression_score >= Decimal("3")
    engine.dispose_all()
