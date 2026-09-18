"""Close orders need stable logical ids for broker-side deduplication."""

import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from brokers.broker.types import OrderStatus, OrderType
from quant.contracts.aggregates import Portfolio


def _status(status=OrderStatus.FILLED, quantity=4, filled_quantity=4, price=100.0):
    return SimpleNamespace(
        status=status,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=price,
        instrument=SimpleNamespace(symbol="CRUDEOIL 17 AUG 7200 CALL"),
        timestamp=datetime.now().isoformat(),
    )


def _adapter(broker):
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = broker
    adapter._order_poll_interval = 0.001
    adapter._order_poll_timeout = 0.05
    adapter._close_slippage_tol = 0.02
    adapter._executing_signal_ids = set()
    adapter._executing_lock = threading.Lock()
    return adapter


def test_close_order_has_stable_logical_id():
    broker = MagicMock()
    broker.place_order.return_value = SimpleNamespace(order_id="BROKER-1", quantity=4)
    broker.get_order_status.return_value = _status()
    adapter = _adapter(broker)

    adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL",
        "SELL",
        4,
        Portfolio.create_default(),
        reference_price=100.0,
    )

    order = broker.place_order.call_args.args[0]
    logical_id = getattr(order, "user_order_id", "")
    assert logical_id
    assert logical_id.startswith("close:")


def test_repeated_close_uses_same_logical_id():
    broker = MagicMock()
    broker.place_order.return_value = SimpleNamespace(order_id="BROKER-1", quantity=4)
    broker.get_order_status.return_value = _status()
    adapter = _adapter(broker)

    for _ in range(2):
        adapter.close_position(
            "CRUDEOIL 17 AUG 7200 CALL",
            "SELL",
            4,
            Portfolio.create_default(),
            reference_price=100.0,
        )

    first_id = getattr(broker.place_order.call_args_list[0].args[0], "user_order_id", "")
    second_id = getattr(broker.place_order.call_args_list[1].args[0], "user_order_id", "")
    assert first_id == second_id


def test_fallback_close_shares_the_economic_id():
    broker = MagicMock()
    broker.place_order.side_effect = [
        SimpleNamespace(order_id="COLLAR-1", quantity=4),
        SimpleNamespace(order_id="FALLBACK-1", quantity=4),
    ]
    broker.get_order_status.side_effect = [
        _status(status=OrderStatus.CANCELLED, filled_quantity=0),
        _status(status=OrderStatus.FILLED, filled_quantity=4, price=98.0),
    ]
    adapter = _adapter(broker)

    adapter.close_position(
        "CRUDEOIL 17 AUG 7200 CALL",
        "SELL",
        4,
        Portfolio.create_default(),
        reference_price=100.0,
    )

    collar_order, fallback_order = (
        broker.place_order.call_args_list[0].args[0],
        broker.place_order.call_args_list[1].args[0],
    )
    collar_id = getattr(collar_order, "user_order_id", "")
    fallback_id = getattr(fallback_order, "user_order_id", "")
    assert collar_id.startswith("close:")
    assert fallback_id == collar_id
