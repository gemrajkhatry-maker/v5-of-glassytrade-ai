"""C4: durable order state-machine persistence (SQLiteStorageAdapter).

A crash between place_order and the fill ack must not silently lose an order:
every order row records its state, and anything not in a terminal state is
"in-flight" and surfaced for reconciliation on restart.
"""
from __future__ import annotations

import pytest

from app.infrastructure.storage.database import (
    ORDER_TERMINAL_STATES,
    SQLiteStorageAdapter,
)


@pytest.fixture
def storage(tmp_path):
    s = SQLiteStorageAdapter(str(tmp_path / "orders.db"))
    yield s
    s.close()


def _order(order_id="ord-1", symbol="NIFTY 24800 CE", status="SUBMITTED", **kw):
    base = {
        "order_id": order_id,
        "signal_id": order_id,
        "symbol": symbol,
        "side": "BUY",
        "quantity": 65.0,
        "order_type": "LIMIT",
        "price": 101.0,
        "status": status,
        "reason": "test",
        "submitted_at": "t0",
        "updated_at": "t0",
    }
    base.update(kw)
    return base


def test_save_and_load_order(storage):
    storage.save_order(_order())
    rows = storage.load_orders()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ord-1"
    assert rows[0]["symbol"] == "NIFTY 24800 CE"
    assert rows[0]["status"] == "SUBMITTED"
    assert rows[0]["quantity"] == pytest.approx(65.0)


def test_update_order_status_to_filled(storage):
    storage.save_order(_order())
    storage.update_order_status(
        "ord-1", "FILLED",
        broker_order_id="DHAN-123", filled_quantity=65.0, avg_fill_price=100.5,
    )
    rows = storage.load_orders(status="FILLED")
    assert len(rows) == 1
    assert rows[0]["broker_order_id"] == "DHAN-123"
    assert rows[0]["filled_quantity"] == pytest.approx(65.0)
    assert rows[0]["avg_fill_price"] == pytest.approx(100.5)


def test_load_inflight_excludes_terminal(storage):
    storage.save_order(_order(order_id="o-sub", status="SUBMITTED"))
    storage.save_order(_order(order_id="o-fill", status="FILLED"))
    storage.save_order(_order(order_id="o-rej", status="REJECTED"))
    storage.save_order(_order(order_id="o-cancel", status="CANCELLED"))

    inflight = storage.load_inflight_orders()
    ids = {o["order_id"] for o in inflight}
    assert ids == {"o-sub"}, f"only non-terminal orders are in-flight, got {ids}"
    assert ORDER_TERMINAL_STATES == {"FILLED", "REJECTED", "CANCELLED", "EXPIRED"}


def test_load_orders_filter_by_symbol(storage):
    storage.save_order(_order(order_id="a", symbol="NIFTY 24800 CE"))
    storage.save_order(_order(order_id="b", symbol="BANKNIFTY 51000 PE"))
    rows = storage.load_orders(symbol="BANKNIFTY 51000 PE")
    assert [r["order_id"] for r in rows] == ["b"]


def test_save_order_is_upsert(storage):
    storage.save_order(_order(status="SUBMITTED"))
    storage.save_order(_order(status="FILLED"))  # same order_id -> replace
    rows = storage.load_orders()
    assert len(rows) == 1
    assert rows[0]["status"] == "FILLED"
