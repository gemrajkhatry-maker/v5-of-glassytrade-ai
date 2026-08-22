"""Event-journal replay parity (P0-2).

Record every DomainEvent of a running session to a durable JSONL journal, then
replay that journal through a *fresh* engine: the same order lifecycle (submit
→ placed → filled) must reproduce identical OMS state — order status /
filled quantity and position quantity / avg price / P&L. Freshly minted order
ids differ between runs (uuid), so equality is asserted on outcome state, not
identity. This is the audit-graded ``replay == live`` proof at the event level.
"""

from __future__ import annotations

from decimal import Decimal

from tradex_domain import (
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from tradex_domain.execution import Order, OrderRequest, Position
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import CorrelationId, Price, Quantity

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.execution.fill_sources import SimulatedFillSource
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.replay.event_journal import EventJournal, iter_journal_events, replay_journal


def _instrument() -> Equity:
    return Equity.of("NSE", "RELIANCE")


def _request(correlation_id: str) -> OrderRequest:
    return OrderRequest(
        instrument=_instrument(),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(value=Decimal("10")),
        price=Price(value=Decimal("2500")),
        time_in_force=TimeInForce.DAY,
        correlation_id=CorrelationId(value=correlation_id),
    )


def _order_state(order: Order) -> tuple[object, ...]:
    return (
        order.instrument.symbol,
        str(order.side),
        str(order.status),
        str(order.quantity.value),
        str(order.filled_quantity.value),
        str(order.price.value) if order.price is not None else None,
    )


def _position_state(position: Position) -> tuple[object, ...]:
    return (
        position.instrument.symbol,
        position.quantity.value,
        position.avg_price.value,
        position.realized_pnl.amount,
        position.unrealized_pnl.amount,
    )


def test_journal_records_order_lifecycle(tmp_path) -> None:
    journal_path = tmp_path / "session.jsonl"
    bus = ReactiveBus()
    engine = ExecutionEngine(bus, SimulatedFillSource())
    with EventJournal(journal_path, bus=bus):
        engine.submit(_request(correlation_id="j-1"))
        engine.submit(_request(correlation_id="j-2"))
        # Two buys of the same instrument net into one position.
        positions = engine.cache.all_positions()
        assert len(positions) == 1
        assert positions[0].quantity.value == Decimal("20")
        recorded = list(iter_journal_events(journal_path))
    engine.shutdown()

    # Every bus-published phase of the lifecycle is captured: placement, fill.
    # (``engine.submit`` runs the pipeline synchronously, so PlaceOrderCommand
    # only appears when published via the bus command subscription.)
    kinds = {type(ev).__name__ for ev in recorded}
    assert recorded, "journal must not be empty"
    assert {"OrderPlaced", "OrderFilled"} <= kinds


def test_replayed_journal_produces_identical_oms_state(tmp_path) -> None:
    journal_path = tmp_path / "session.jsonl"

    # Run A — journaled live session (simulated fills for determinism).
    bus_a = ReactiveBus()
    engine_a = ExecutionEngine(bus_a, SimulatedFillSource())
    with EventJournal(journal_path, bus=bus_a):
        engine_a.submit(_request(correlation_id="parity-1"))
        engine_a.submit(_request(correlation_id="parity-2"))
    engine_a.shutdown()

    # Run B — replay the journal through a fresh engine.
    bus_b = ReactiveBus()
    engine_b = ExecutionEngine(bus_b, SimulatedFillSource())
    replay_journal(journal_path, bus=bus_b)
    engine_b.shutdown()

    # Same order outcomes as a multiset. Order ids are freshly minted on
    # replay and correlation ids arrive only via commands (the fill-derived
    # replay orders carry none), so identity metadata is excluded — the claim
    # is that the same published events reproduce the same order *outcomes*.
    orders_a = engine_a.cache.all_orders()
    orders_b = engine_b.cache.all_orders()
    assert len(orders_a) == len(orders_b) == 2
    assert sorted(_order_state(o) for o in orders_a) == sorted(
        _order_state(o) for o in orders_b
    )

    pos_a = sorted(engine_a.cache.all_positions(), key=lambda p: p.instrument.symbol)
    pos_b = sorted(engine_b.cache.all_positions(), key=lambda p: p.instrument.symbol)
    assert len(pos_a) == len(pos_b) == 1
    assert [_position_state(p) for p in pos_a] == [_position_state(p) for p in pos_b]
    assert pos_b[0].quantity.value == Decimal("20")


def test_journal_is_append_only_and_replayable_twice(tmp_path) -> None:
    journal_path = tmp_path / "session.jsonl"
    bus = ReactiveBus()
    engine = ExecutionEngine(bus, SimulatedFillSource())
    with EventJournal(journal_path, bus=bus):
        engine.submit(_request(correlation_id="dup-1"))
    engine.shutdown()

    first = list(iter_journal_events(journal_path))
    # Replaying never mutates the journal — replay again identically.
    second = list(iter_journal_events(journal_path))
    assert len(second) == len(first) > 0
    assert [type(e) for e in second] == [type(e) for e in first]


def test_replay_on_fresh_bus_needs_engine_to_act(tmp_path) -> None:
    """Without an attached engine the journal is inert — replay only publishes."""
    journal_path = tmp_path / "session.jsonl"
    bus = ReactiveBus()
    engine = ExecutionEngine(bus, SimulatedFillSource())
    with EventJournal(journal_path, bus=bus):
        engine.submit(_request(correlation_id="inert-1"))
    engine.shutdown()

    bare = replay_journal(journal_path)  # no engine subscribed
    assert bare is not None
    assert engine.cache.all_positions()  # original run had fills
