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


def test_close_fallback_has_one_economic_identity():
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
