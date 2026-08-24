"""Anti-fragility tests: duplicate-fill dedup and kill-switch state safety."""

from __future__ import annotations

from decimal import Decimal

from tradex_domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from tradex_domain.events import OrderFilled
from tradex_domain.execution import Fill, Order, OrderRequest
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import OrderId, Price, Quantity

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.execution.fill_sources import SimulatedFillSource
from tradex_trading.execution.trading_cache import TradingCache
from tradex_trading.reactive.bus import ReactiveBus


def _eq() -> Equity:
    return Equity.of("NSE", "RELIANCE")


def _fill(fill_id: str | None) -> Fill:
    return Fill(
        order_id=OrderId(value="o1"),
        instrument=_eq(),
        side=OrderSide.BUY,
        quantity=Quantity(Decimal("10")),
        price=Price(Decimal("100")),
        fill_id=fill_id,
    )


def _engine() -> tuple[ExecutionEngine, ReactiveBus]:
    bus = ReactiveBus()
    engine = ExecutionEngine(
        bus=bus,
        fill_source=SimulatedFillSource(),
        cache=TradingCache(),
    )
    return engine, bus


def test_duplicate_fill_with_fill_id_applied_once() -> None:
    """A re-published fill (same venue trade id) never double-applies."""
    engine, bus = _engine()
    bus.publish(OrderFilled(fill=_fill(fill_id="t1")))
    bus.publish(OrderFilled(fill=_fill(fill_id="t1")))
    positions = engine.cache.all_positions()
    assert len(positions) == 1
    assert positions[0].quantity.value == Decimal("10")


def test_duplicate_fill_without_fill_id_deduped_by_fingerprint() -> None:
    """Without a venue trade id, the (order, side, qty, price) fingerprint
    still collapses a re-publish to a single fill."""
    engine, bus = _engine()
    bus.publish(OrderFilled(fill=_fill(fill_id=None)))
    bus.publish(OrderFilled(fill=_fill(fill_id=None)))
    positions = engine.cache.all_positions()
    assert len(positions) == 1
    assert positions[0].quantity.value == Decimal("10")


def test_distinct_partial_fills_both_applied() -> None:
    """Two equal-lot partial fills with distinct venue ids are each applied in
    full — never mistaken for a re-publish of the first."""
    engine, bus = _engine()
    engine.cache.update_order(
        Order(
            order_id=OrderId(value="o1"),
            instrument=_eq(),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Quantity(Decimal("30")),
            price=Price(Decimal("100")),
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.ACK,
        )
    )
    bus.publish(OrderFilled(fill=_fill(fill_id="t1")))
    bus.publish(OrderFilled(fill=_fill(fill_id="t2")))
    positions = engine.cache.all_positions()
    assert positions[0].quantity.value == Decimal("20")
    order = engine.cache.get_order(OrderId(value="o1"))
    assert order is not None
    assert order.status is OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity.value == Decimal("20")


def test_kill_switch_after_fill_preserves_position() -> None:
    """Tripping the kill switch must not corrupt already-booked positions."""
    engine, _ = _engine()
    request = OrderRequest(
        instrument=_eq(),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(Decimal("10")),
        price=Price(Decimal("100")),
    )
    receipt = engine.submit(request)
    assert receipt.status is OrderStatus.FILLED
    engine.trip_kill_switch(reason="test")
    positions = engine.cache.all_positions()
    assert len(positions) == 1
    assert positions[0].quantity.value == Decimal("10")
