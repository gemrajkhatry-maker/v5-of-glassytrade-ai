"""B3: durable order ledger truthfulness at the timeout boundary.

The C4 timeout path previously persisted CANCELLED unconditionally — even when
the cancel request itself failed (order may still be live at the broker) and
without checking whether a fill raced the cancel. An actually-filled order
would be recorded CANCELLED while the engine saw a failed entry: untracked
live exposure. These tests pin the honest contract:

- cancel request fails          -> durable row UNKNOWN (reconcile-required)
- fill races the cancel         -> position honored, row FILLED
- partial fill frozen by cancel -> row FILLED with the fractional quantity
- clean cancel, no fill         -> row CANCELLED
- duplicate WS fill updates     -> idempotent (absolute values, no accumulation)
"""

import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from brokers.broker.types import OrderStatus
from quant.contracts.aggregates import Portfolio
from quant.contracts.enums import SetupType, SignalType, Source
from quant.contracts.entities import Signal


class _RecordingStorage:
    """Minimal IStorage double capturing durable order writes."""

    def __init__(self):
        self.saved: list[dict] = []
        self.updates: list[tuple] = []

    def save_order(self, order: dict) -> None:
        self.saved.append(dict(order))

    def update_order_status(self, order_id, status, *, broker_order_id=None,
                            filled_quantity=None, avg_fill_price=None) -> None:
        self.updates.append((order_id, status, broker_order_id, filled_quantity, avg_fill_price))


def _adapter(broker: MagicMock) -> DhanBrokerAdapter:
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = broker
    adapter._order_poll_interval = 0.001
    adapter._order_poll_timeout = 0.05
    adapter._config = None
    adapter._storage = _RecordingStorage()
    adapter._executing_signal_ids = set()
    adapter._executing_lock = threading.Lock()
    return adapter


def _signal() -> Signal:
    return Signal(
        type=SignalType.BUY,
        price=100.0,
        reason="timeout truthfulness",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp="2026-09-04T10:00:00+05:30",
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
        metadata={"order_quantity": 4},
    )


def _status(status=OrderStatus.FILLED, quantity=4, filled_quantity=4, price=100.0):
    return SimpleNamespace(
        status=status,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=price,
        instrument=SimpleNamespace(symbol="CRUDEOIL 17 AUG 7200 CALL"),
        timestamp=datetime.now().isoformat(),
    )


def _broker_poll_timeout() -> MagicMock:
    """Broker whose orders never reach terminal status inside the poll window."""
    broker = MagicMock()
    broker.place_order.return_value = SimpleNamespace(order_id="ORD-T", quantity=4)
    broker.get_order_status.return_value = _status(status=OrderStatus.OPEN, filled_quantity=0)
    return broker


def _last_row_status(storage: _RecordingStorage) -> str:
    return storage.updates[-1][1]


# ---------------------------------------------------------------------------
# Timeout boundary truthfulness
# ---------------------------------------------------------------------------


def test_cancel_failure_after_timeout_persists_unknown_not_cancelled():
    broker = _broker_poll_timeout()
    broker.cancel_order.side_effect = RuntimeError("circuit down")
    adapter = _adapter(broker)

    assert adapter.execute_order(_signal(), Portfolio.create_default(), "CRUDEOIL") is None
    assert _last_row_status(adapter._storage) == "UNKNOWN"


def test_fill_racing_cancel_is_honored_not_cancelled():
    broker = _broker_poll_timeout()
    broker.cancel_order.return_value = None  # cancel accepted...
    broker.get_order_status.return_value = _status(status=OrderStatus.FILLED)  # ...but it filled first
    adapter = _adapter(broker)

    position = adapter.execute_order(_signal(), Portfolio.create_default(), "CRUDEOIL")
    assert position is not None, "a raced fill must be honored, not dropped"
    assert _last_row_status(adapter._storage) == "FILLED"


def test_partial_fill_frozen_by_cancel_is_persisted():
    broker = _broker_poll_timeout()
    broker.cancel_order.return_value = None
    # Still OPEN with 2/4 filled at the moment of the post-cancel read.
    broker.get_order_status.return_value = _status(
        status=OrderStatus.OPEN, filled_quantity=2, price=99.5
    )
    adapter = _adapter(broker)

    assert adapter.execute_order(_signal(), Portfolio.create_default(), "CRUDEOIL") is None
    order_id, status, broker_order_id, filled, avg = adapter._storage.updates[-1]
    assert status == "FILLED"
    assert filled == 2.0
    assert avg == 99.5
    assert broker_order_id == "ORD-T"


def test_clean_cancel_persists_cancelled():
    broker = _broker_poll_timeout()
    broker.cancel_order.return_value = None
    broker.get_order_status.return_value = _status(status=OrderStatus.CANCELLED, filled_quantity=0)
    adapter = _adapter(broker)

    assert adapter.execute_order(_signal(), Portfolio.create_default(), "CRUDEOIL") is None
    assert _last_row_status(adapter._storage) == "CANCELLED"


# ---------------------------------------------------------------------------
# WS feed persistence idempotency (duplicate updates converge)
# ---------------------------------------------------------------------------


def test_duplicate_ws_fill_updates_are_idempotent():
    broker = MagicMock()
    adapter = _adapter(broker)
    adapter._persist_order_terminal(_signal(), "SUBMITTED", broker_order_id="ORD-W")
    storage = adapter._storage
    base = len(storage.updates)

    snap = {"order_id": "ORD-W", "status": OrderStatus.FILLED, "filled_quantity": 4.0,
            "average_fill_price": 100.0}
    adapter._on_order_feed_update(snap)
    adapter._on_order_feed_update(snap)  # replayed/duplicate push
    adapter._on_order_feed_update(snap)  # REST/WS race duplicate

    fills = [u for u in storage.updates[base:] if u[1] == "FILLED"]
    assert len(fills) == 3
    # Absolute values, not increments: every duplicate writes the same row state.
    assert all(u[3] == 4.0 and u[4] == 100.0 for u in fills)


def test_ws_non_terminal_transition_leaves_row_inflight():
    broker = MagicMock()
    adapter = _adapter(broker)
    adapter._persist_order_terminal(_signal(), "SUBMITTED", broker_order_id="ORD-N")
    storage = adapter._storage
    base = len(storage.updates)

    adapter._on_order_feed_update({"order_id": "ORD-N", "status": OrderStatus.OPEN,
                                   "filled_quantity": 0.0, "average_fill_price": 0.0})

    assert len(storage.updates) == base, "non-terminal push must not touch the durable row"
