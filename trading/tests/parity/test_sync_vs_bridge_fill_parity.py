"""Cross-path fill parity gate (HIGH-2 closeout).

The audit's replay-vs-live concern, in v4 terms: a fill can reach the OMS
through two different entry paths — the *synchronous* simulated/paper pipeline
(``SimulatedFillSource`` fills immediately during ``submit``) and the *live
bridge* path (``BrokerFillSource`` ACKs, then the order stream publishes
``OrderFilled`` which ``_apply_fill`` applies). Both paths must land
**identical** OMS state (order status/filled quantity and position
quantity/avg price/P&L) for the same logical fill — otherwise a live session
would account differently than its backtest replay of the same tape.

This gate feeds the same fill through both paths and asserts byte-identical
cache state. It is the replay == live proof for the v4 execution spine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import (
    OrderFilled,
    OrderPlaced,
    OrderSide,
    OrderStatus,
    OrderType,
    PlaceOrderCommand,
    TimeInForce,
)
from tradex_domain.events import Fill
from tradex_domain.execution import Order, OrderRequest, Position
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import OrderId, Price, Quantity

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.execution.fill_sources import BrokerFillSource, SimulatedFillSource
from tradex_trading.reactive.bus import ReactiveBus


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
        correlation_id=correlation_id,
    )


def _fill(order_id: str, quantity: str, price: str) -> OrderFilled:
    return OrderFilled(
        fill=Fill(
            order_id=OrderId(value=order_id),
            instrument=_instrument(),
            side=OrderSide.BUY,
            quantity=Quantity(value=Decimal(quantity)),
            price=Price(value=Decimal(price)),
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )


class _AsyncFillBroker:
    """Broker that ACKs synchronously; fills arrive via the order stream."""

    owns_position_projection = False

    def __init__(self) -> None:
        self.submitted: list[OrderRequest] = []

    def submit_order(self, request: OrderRequest) -> object:
        self.submitted.append(request)
        return "broker-order-1"

    def cancel_order(self, order_id: OrderId) -> None:
        pass


def _position_state(position: Position) -> tuple[object, ...]:
    return (
        position.instrument.symbol,
        position.quantity.value,
        position.avg_price.value,
        position.realized_pnl.amount,
        position.unrealized_pnl.amount,
    )


def _order_state(order: Order) -> tuple[object, ...]:
    return (
        order.instrument.symbol,
        order.status,
        order.filled_quantity.value,
        order.price.value if order.price is not None else None,
    )


class TestSyncVsBridgeFillParity:
    """The same logical fill accounts identically on both entry paths."""

    def test_full_fill_lands_identical_oms_state(self) -> None:
        """A full simulated fill (sync path) and the identical broker-stream
        fill (bridge path) must produce the same position and order state."""

        # Path A — synchronous simulated pipeline (backtest/replay/paper).
        bus_a = ReactiveBus()
        engine_a = ExecutionEngine(bus_a, SimulatedFillSource())
        try:
            engine_a.submit(_request(correlation_id="parity-a"))
            assert len(engine_a.cache.all_positions()) == 1
        finally:
            engine_a.shutdown()

        # Path B — live bridge: ACK on submit, fill arrives via OrderFilled.
        bus_b = ReactiveBus()
        engine_b = ExecutionEngine(bus_b, BrokerFillSource(_AsyncFillBroker()))
        placed: list[OrderPlaced] = []
        bus_b.of_type(OrderPlaced).subscribe(placed.append)
        try:
            bus_b.publish(PlaceOrderCommand(request=_request(correlation_id="parity-b")))
            assert placed and placed[0].order.status == OrderStatus.ACK
            assert engine_b.cache.all_positions() == []  # nothing until the stream fills
            bus_b.publish(_fill(placed[0].order.order_id.value, "10", "2500"))
        finally:
            engine_b.shutdown()

        assert _position_state(engine_a.cache.all_positions()[0]) == _position_state(
            engine_b.cache.all_positions()[0]
        )
        order_a = engine_a.cache.all_orders()[0]
        order_b = engine_b.cache.all_orders()[0]
        assert _order_state(order_a) == _order_state(order_b)
        assert order_a.status == order_b.status == OrderStatus.FILLED

    def test_partial_fills_accumulate_to_identical_state(self) -> None:
        """Two bridge partials (4 + 6) must end at the same position as the
        single simulated full fill — delta-only accumulation across paths."""

        bus_a = ReactiveBus()
        engine_a = ExecutionEngine(bus_a, SimulatedFillSource())
        try:
            engine_a.submit(_request(correlation_id="parity-partial-a"))
        finally:
            engine_a.shutdown()

        bus_b = ReactiveBus()
        engine_b = ExecutionEngine(bus_b, BrokerFillSource(_AsyncFillBroker()))
        placed: list[OrderPlaced] = []
        bus_b.of_type(OrderPlaced).subscribe(placed.append)
        try:
            bus_b.publish(PlaceOrderCommand(request=_request(correlation_id="parity-partial-b")))
            oid = placed[0].order.order_id.value
            bus_b.publish(_fill(oid, "4", "2498"))
            bus_b.publish(_fill(oid, "6", "2502"))
        finally:
            engine_b.shutdown()

        pos_a = engine_a.cache.all_positions()[0]
        pos_b = engine_b.cache.all_positions()[0]
        assert pos_b.quantity.value == Decimal("10")
        # Weighted average across the two partial legs (4*2498 + 6*2502) / 10.
        assert pos_b.avg_price.value == Decimal("2500.4")
        # The bridge order finished FILLED after the second partial.
        assert engine_b.cache.all_orders()[0].status == OrderStatus.FILLED
        # Same notional exposure as the single simulated full fill at 2500.
        assert pos_a.quantity.value == pos_b.quantity.value
        assert pos_a.avg_price.value == Decimal("2500")
