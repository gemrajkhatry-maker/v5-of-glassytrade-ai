"""BookFillSource — tick-level L2 order-book matching (P1a scalping realism).

A marketable order sweeps the book from the touch, consuming level by level;
the fill price is the volume-weighted average of the levels consumed. Limit
orders resting outside the book get no fill; thin books produce partial
fills. The book is consumed across fills, exactly like a real venue.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import Depth, Equity, OrderRequest, Price, Quantity
from tradex_domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from tradex_domain.execution import Fill

from tradex_trading.execution.book_fill_source import BookFillSource
from tradex_trading.execution.latency_models import FixedLatencyModel

TS = datetime(2026, 8, 1, 9, 15, tzinfo=UTC)
INST = Equity.of("NSE", "RELIANCE")


def _request(
    side: OrderSide,
    qty: str,
    price: str | None = None,
    order_type: OrderType = OrderType.MARKET,
) -> OrderRequest:
    return OrderRequest(
        instrument=INST,
        side=side,
        order_type=order_type,
        quantity=Quantity(value=Decimal(qty)),
        price=Price(value=Decimal(price)) if price is not None else None,
        time_in_force=TimeInForce.DAY,
        reference_timestamp=TS,
    )


def _book(bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> Depth:
    return Depth(
        instrument=INST,
        bids=tuple(
            (Price(value=Decimal(p)), Quantity(value=Decimal(q))) for p, q in bids
        ),
        asks=tuple(
            (Price(value=Decimal(p)), Quantity(value=Decimal(q))) for p, q in asks
        ),
        timestamp=TS,
    )


def test_market_buy_sweeps_asks_at_vwap() -> None:
    """A 15-lot market BUY consumes 100.0/50 + 100.5/50 → VWAP (100*10+100.5*5)/15."""
    source = BookFillSource()
    source.update_depth(_book([("99.5", "50")], [("100.0", "10"), ("100.5", "50")]))

    order, fill = source.submit(_request(OrderSide.BUY, "15"))

    assert fill is not None
    assert fill.quantity.value == Decimal("15")
    assert fill.price.value == Decimal("100.1666666666666666666666667")
    assert order.status is OrderStatus.FILLED


def test_market_sell_sweeps_bids_at_vwap() -> None:
    source = BookFillSource()
    source.update_depth(_book([("99.0", "10"), ("98.5", "50")], [("100.0", "50")]))

    order, fill = source.submit(_request(OrderSide.SELL, "20"))

    assert fill is not None
    assert fill.quantity.value == Decimal("20")
    assert fill.price.value == Decimal("98.75")  # (99*10 + 98.5*10) / 20
    assert order.status is OrderStatus.FILLED


def test_partial_fill_when_book_exhausted() -> None:
    """Book has only 8 lots vs a 15-lot order → 8-lot fill, order PARTIALLY_FILLED."""
    source = BookFillSource()
    source.update_depth(_book([("99.5", "50")], [("100.0", "8")]))

    order, fill = source.submit(_request(OrderSide.BUY, "15"))

    assert fill is not None
    assert fill.quantity.value == Decimal("8")
    assert fill.price.value == Decimal("100")
    assert order.status is OrderStatus.PARTIALLY_FILLED


def test_limit_buy_below_best_ask_gets_no_fill() -> None:
    """A limit BUY at 99.5 rests below the 100.0 ask → ACK, no fill."""
    source = BookFillSource()
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))

    order, fill = source.submit(
        _request(OrderSide.BUY, "10", price="99.5", order_type=OrderType.LIMIT)
    )

    assert fill is None
    assert order.status is OrderStatus.ACK


def test_limit_buy_at_or_above_best_ask_fills() -> None:
    source = BookFillSource()
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))

    order, fill = source.submit(
        _request(OrderSide.BUY, "10", price="100.0", order_type=OrderType.LIMIT)
    )

    assert fill is not None
    assert fill.price.value == Decimal("100")
    assert order.status is OrderStatus.FILLED


def test_limit_sell_above_best_bid_gets_no_fill() -> None:
    source = BookFillSource()
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))

    order, fill = source.submit(
        _request(OrderSide.SELL, "10", price="99.5", order_type=OrderType.LIMIT)
    )

    assert fill is None
    assert order.status is OrderStatus.ACK


def test_book_is_consumed_across_fills() -> None:
    """Two sweeps share one book: the second sees the reduced depth."""
    source = BookFillSource()
    source.update_depth(_book([("99.0", "50")], [("100.0", "10"), ("100.5", "10")]))

    # First order takes all of 100.0 and half of 100.5.
    order1, fill1 = source.submit(_request(OrderSide.BUY, "15"))
    assert fill1 is not None
    assert fill1.price.value == Decimal("100.1666666666666666666666667")

    # Second order takes the remaining 5 lots of 100.5.
    order2, fill2 = source.submit(_request(OrderSide.BUY, "5"))
    assert fill2 is not None
    assert fill2.quantity.value == Decimal("5")
    assert fill2.price.value == Decimal("100.5")
    assert order2.status is OrderStatus.FILLED

    # Third order finds the asks exhausted → no fill.
    order3, fill3 = source.submit(_request(OrderSide.BUY, "5"))
    assert fill3 is None
    assert order3.status is OrderStatus.ACK


def test_empty_book_or_missing_side_gets_no_fill() -> None:
    source = BookFillSource()
    order, fill = source.submit(_request(OrderSide.BUY, "10"))
    assert fill is None
    assert order.status is OrderStatus.ACK

    # Book with bids only: a BUY has nothing to sweep.
    source.update_depth(_book([("99.0", "50")], []))
    order, fill = source.submit(_request(OrderSide.BUY, "10"))
    assert fill is None


def test_limit_buy_rests_then_fills_when_ask_drops() -> None:
    """A resting limit fills (via OrderFilled) once the book moves to its price."""
    from tradex_domain.events import OrderFilled

    from tradex_trading.reactive.bus import ReactiveBus

    bus = ReactiveBus()
    fills: list[Fill] = []
    bus.of_type(OrderFilled).subscribe(lambda ev: fills.append(ev.fill))
    source = BookFillSource()
    source.bind_bus(bus)
    source.update_depth(_book([("99.0", "50")], [("100.5", "50")]))

    # Limit BUY at 100.0 rests below the 100.5 ask → no immediate fill.
    order, fill = source.submit(
        _request(OrderSide.BUY, "10", price="100.0", order_type=OrderType.LIMIT)
    )
    assert fill is None
    assert order.status is OrderStatus.ACK
    assert fills == []

    # Ask drops to 100.0 → the resting order sweeps it and fills.
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))
    assert len(fills) == 1
    assert fills[0].quantity.value == Decimal("10")
    assert fills[0].price.value == Decimal("100.0")
    assert fills[0].order_id == order.order_id


def test_resting_sell_fills_when_bid_rises() -> None:
    from tradex_domain.events import OrderFilled

    from tradex_trading.reactive.bus import ReactiveBus

    bus = ReactiveBus()
    fills: list[Fill] = []
    bus.of_type(OrderFilled).subscribe(lambda ev: fills.append(ev.fill))
    source = BookFillSource()
    source.bind_bus(bus)
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))

    order, fill = source.submit(
        _request(OrderSide.SELL, "10", price="100.5", order_type=OrderType.LIMIT)
    )
    assert fill is None  # rests above the 99.0 bid

    source.update_depth(_book([("100.5", "50")], [("101.0", "50")]))
    assert len(fills) == 1
    assert fills[0].quantity.value == Decimal("10")
    assert fills[0].price.value == Decimal("100.5")


def test_partial_remainder_keeps_working() -> None:
    """A partial fill's remainder rests and fills when more size appears."""
    from tradex_domain.events import OrderFilled

    from tradex_trading.reactive.bus import ReactiveBus

    bus = ReactiveBus()
    fills: list[Fill] = []
    bus.of_type(OrderFilled).subscribe(lambda ev: fills.append(ev.fill))
    source = BookFillSource()
    source.bind_bus(bus)
    source.update_depth(_book([("99.0", "50")], [("100.0", "8")]))

    order, fill = source.submit(_request(OrderSide.BUY, "15"))
    assert fill is not None and fill.quantity.value == Decimal("8")
    assert order.status is OrderStatus.PARTIALLY_FILLED

    # Fresh 10 lots appear → the resting 7-lot remainder sweeps them.
    source.update_depth(_book([("99.0", "50")], [("100.0", "10")]))
    assert len(fills) == 1
    assert fills[0].quantity.value == Decimal("7")
    assert fills[0].price.value == Decimal("100.0")
    assert fills[0].order_id == order.order_id


def test_market_remainder_fills_next_size() -> None:
    """A market order's unfilled remainder stays marketable and sweeps new size."""
    from tradex_domain.events import OrderFilled

    from tradex_trading.reactive.bus import ReactiveBus

    bus = ReactiveBus()
    fills: list[Fill] = []
    bus.of_type(OrderFilled).subscribe(lambda ev: fills.append(ev.fill))
    source = BookFillSource()
    source.bind_bus(bus)
    source.update_depth(_book([("99.0", "50")], [("100.0", "5")]))

    order, fill = source.submit(_request(OrderSide.BUY, "10"))
    assert fill is not None and fill.quantity.value == Decimal("5")
    assert order.status is OrderStatus.PARTIALLY_FILLED

    # 20 lots appear → the marketable 5-lot remainder fills at the touch.
    source.update_depth(_book([("99.0", "50")], [("100.0", "20")]))
    assert len(fills) == 1
    assert fills[0].quantity.value == Decimal("5")
    assert fills[0].price.value == Decimal("100.0")
    assert fills[0].order_id == order.order_id


def test_cancel_removes_resting_order() -> None:
    from tradex_domain.events import OrderFilled

    from tradex_trading.reactive.bus import ReactiveBus

    bus = ReactiveBus()
    fills: list[Fill] = []
    bus.of_type(OrderFilled).subscribe(lambda ev: fills.append(ev.fill))
    source = BookFillSource()
    source.bind_bus(bus)
    source.update_depth(_book([("99.0", "50")], [("100.5", "50")]))

    order, fill = source.submit(
        _request(OrderSide.BUY, "10", price="100.0", order_type=OrderType.LIMIT)
    )
    assert fill is None

    source.cancel(order.order_id)
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))
    assert fills == []  # cancelled resting order never fills


def test_equal_lot_partials_at_same_price_both_apply() -> None:
    """Venue-side fill_ids keep equal-lot partials distinct (order-aware dedup).

    A 10-lot market BUY against a 5-lot book partially fills; the resting
    5-lot remainder then fills at the SAME price from a fresh snapshot.
    Without distinct fill_ids the engine's inbound-fill bridge would treat
    the second 5@100.0 as a re-publish of the first and skip it — position 5
    instead of 10.
    """
    from tradex_trading.execution.engine import ExecutionEngine
    from tradex_trading.execution.trading_cache import TradingCache
    from tradex_trading.reactive.bus import ReactiveBus

    from tradex_domain.execution import OrderRequest as _OR

    bus = ReactiveBus()
    cache = TradingCache()
    source = BookFillSource()
    source.bind_bus(bus)
    engine = ExecutionEngine(bus, source, cache=cache)

    source.update_depth(_book([("99.0", "50")], [("100.0", "5")]))
    request = _request(OrderSide.BUY, "10")
    receipt = engine.submit(_OR(
        instrument=request.instrument, side=request.side,
        order_type=request.order_type, quantity=request.quantity,
        price=request.price, time_in_force=request.time_in_force,
        reference_timestamp=request.reference_timestamp,
    ))
    assert receipt.status.value == "PARTIALLY_FILLED"

    # Fresh 5 lots at the SAME price — the resting remainder fills identically.
    source.update_depth(_book([("99.0", "50")], [("100.0", "5")]))

    position = cache.get_position(INST.symbol)
    assert position is not None
    assert position.quantity.value == Decimal("10")
    assert position.avg_price.value == Decimal("100.0")
    order = cache.get_order(receipt.order_id)
    assert order is not None and order.status is OrderStatus.FILLED
    assert order.filled_quantity.value == Decimal("10")


def test_fill_timestamp_routes_through_latency_model() -> None:
    latency = FixedLatencyModel(delay=timedelta(seconds=2))
    source = BookFillSource(latency_model=latency)
    source.update_depth(_book([("99.0", "50")], [("100.0", "50")]))

    _, fill = source.submit(_request(OrderSide.BUY, "10"))

    assert fill is not None
    assert fill.timestamp == TS + timedelta(seconds=2)
