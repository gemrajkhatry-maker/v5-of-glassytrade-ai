from types import SimpleNamespace
from unittest.mock import MagicMock

from brokers.broker.types import OrderStatus
from quant.contracts.aggregates import Portfolio


def _status(status, filled_quantity, price=100.0):
    return SimpleNamespace(
        status=status,
        quantity=4,
        filled_quantity=filled_quantity,
        average_fill_price=price,
        instrument=SimpleNamespace(symbol="CRUDEOIL 17 AUG 7200 CALL"),
        timestamp="2026-09-18T10:00:00",
    )


def test_late_fill_close_fallback_cannot_double_count_economic_identity():
    from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter

    broker = MagicMock()
    broker.place_order.side_effect = [
        SimpleNamespace(order_id="COLLAR-1", quantity=4),
        SimpleNamespace(order_id="FALLBACK-1", quantity=4),
    ]
    broker.get_order_status.side_effect = [
        _status(OrderStatus.CANCELLED, 0),
        _status(OrderStatus.FILLED, 4, 98.0),
    ]
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = broker
    adapter._order_poll_interval = 0.001
    adapter._order_poll_timeout = 0.05
    adapter._close_slippage_tol = 0.02

    adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL", "SELL", 4,
        Portfolio.create_default(), reference_price=100.0,
    )

    ids = [
        getattr(call.args[0], "user_order_id", "")
        for call in broker.place_order.call_args_list
    ]
    assert ids[0] == ids[1]


def test_live_oms_partial_close_preserves_economic_identity():
    from quant.execution.live_oms import LiveOMS
    from quant.execution.order import Order, Position
    from tests.quant.test_submission_handler_integration import make_signal

    broker = MagicMock()
    broker.close_position.return_value = SimpleNamespace(entry_price=98.0, size=-2)
    position = Position(Order(make_signal(), 4), 100.0, "t", 4.0, _id="position-1")
    oms = LiveOMS(broker, Portfolio.create_default())

    oms.close_partial(position, 0.5, 100.0, "t", "TP1")
    first = broker.close_position.call_args.kwargs.get("close_intent_id")
    oms.close_partial(position, 0.5, 100.0, "t", "TP1")
    second = broker.close_position.call_args.kwargs.get("close_intent_id")

    assert first == second
