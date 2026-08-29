"""C4 async fill feed — Dhan order-update WebSocket.

The feed is a pure optimization over the proven REST poll: every failure is
contained and the adapter falls back to REST, so the critical property under
test is (a) correct normalization/status mapping, (b) buffered dispatch that
never loses an update that raced ahead of waiter registration, and (c) the
adapter's WS-first / REST-fallback orchestration.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter
from app.infrastructure.adapters.dhan_order_feed import (
    DhanOrderUpdateFeed,
    normalize_order_update,
)
from brokers.broker.types import OrderStatus


# ---------------------------------------------------------------------------
# Normalization — casing drift + status mapping
# ---------------------------------------------------------------------------


def _alert(data: dict, type_="order_alert"):
    return {"Type": type_, "Data": data}


def test_normalize_lower_camel_payload():
    snap = normalize_order_update(
        _alert({
            "orderNo": "11245", "status": "TRADED", "quantity": 65,
            "tradedQty": 65, "avgTradedPrice": 101.5,
            "tradingSymbol": "NIFTY 24800 CE", "orderTimestamp": "t1",
        })
    )
    assert snap is not None
    assert snap["order_id"] == "11245"
    assert snap["status"] == OrderStatus.FILLED
    assert snap["raw_status"] == "TRADED"
    assert snap["quantity"] == pytest.approx(65.0)
    assert snap["filled_quantity"] == pytest.approx(65.0)
    assert snap["average_fill_price"] == pytest.approx(101.5)
    assert snap["symbol"] == "NIFTY 24800 CE"
    assert snap["timestamp"] == "t1"


def test_normalize_pascal_case_payload():
    snap = normalize_order_update(
        _alert({
            "OrderNo": "11246", "Status": "REJECTED", "Quantity": 10,
            "TradedQty": 0, "AvgTradedPrice": 0,
        })
    )
    assert snap is not None
    assert snap["order_id"] == "11246"
    assert snap["status"] == OrderStatus.REJECTED
    assert snap["filled_quantity"] == pytest.approx(0.0)


def test_status_mapping_matches_rest_table():
    cases = {
        "TRADED": OrderStatus.FILLED,
        "TRANSIT": OrderStatus.PENDING,
        "PENDING": OrderStatus.PENDING,
        "PART_TRADED": OrderStatus.OPEN,
        "CANCELLED": OrderStatus.CANCELLED,
        "EXPIRED": OrderStatus.CANCELLED,
        "REJECTED": OrderStatus.REJECTED,
    }
    for raw, expected in cases.items():
        snap = normalize_order_update(_alert({"orderNo": "1", "status": raw}))
        assert snap["status"] == expected, raw


def test_unknown_status_is_non_terminal_not_dropped():
    """A wrong terminal guess would strand a live order — default PENDING."""
    snap = normalize_order_update(_alert({"orderNo": "1", "status": "SOMETHING_NEW"}))
    assert snap["status"] == OrderStatus.PENDING


def test_non_order_payloads_are_ignored():
    assert normalize_order_update(None) is None
    assert normalize_order_update({"Type": "order_alert"}) is None          # no Data
    assert normalize_order_update(_alert({"status": "TRADED"})) is None     # no orderNo
    assert normalize_order_update(_alert({"orderNo": "1"}, type_="other")) is None


# ---------------------------------------------------------------------------
# Feed buffering + waiter contract
# ---------------------------------------------------------------------------


@pytest.fixture
def feed():
    return DhanOrderUpdateFeed(client_id="c", access_token="t")  # never started


def test_dispatch_buffers_snapshot(feed):
    feed.inject_update(_alert({"orderNo": "A1", "status": "TRADED", "tradedQty": 5}))
    snap = feed.snapshot("A1")
    assert snap is not None
    assert snap["status"] == OrderStatus.FILLED


def test_waiter_wakes_on_update(feed):
    timer = threading.Timer(
        0.01, lambda: feed.inject_update(_alert({"orderNo": "B1", "status": "TRADED"}))
    )
    timer.start()
    try:
        assert feed.wait_for_update("B1", timeout=2.0) is True
        assert feed.snapshot("B1")["status"] == OrderStatus.FILLED
    finally:
        timer.join()


def test_stale_update_is_visible_via_snapshot_not_wakeup(feed):
    """Contract: updates landing BEFORE wait_for_update are consumed via
    snapshot() (the adapter's loop always checks snapshot first); the stale
    event is cleared so a later wait only wakes on genuinely new updates."""
    feed.inject_update(_alert({"orderNo": "C1", "status": "TRADED"}))
    assert feed.wait_for_update("C1", timeout=0.05) is False
    assert feed.snapshot("C1") is not None


def test_update_racing_ahead_of_registration_is_not_lost(feed):
    """The C4 race: broker pushes the fill before the engine registers a
    waiter — snapshot() must still return it."""
    feed.inject_update(_alert({"orderNo": "D1", "status": "TRADED", "tradedQty": 65}))
    assert feed.wait_for_update("D1", timeout=0.05) is False  # stale event cleared
    snap = feed.snapshot("D1")
    assert snap["filled_quantity"] == pytest.approx(65.0)


def test_buffer_is_bounded(feed):
    for i in range(250):
        feed.inject_update(_alert({"orderNo": f"o{i}", "status": "TRADED"}))
    assert feed.snapshot("o0") is None          # oldest evicted
    assert feed.snapshot("o249") is not None    # newest retained
    assert feed.snapshot("o100") is not None    # within the 200-order window


def test_stop_without_start_is_safe(feed):
    feed.stop()
    assert feed.healthy is False


def test_on_update_callback_receives_normalized_snapshot():
    seen = []
    feed = DhanOrderUpdateFeed(
        client_id="c", access_token="t", on_update=lambda s: seen.append(s)
    )
    feed.inject_update(_alert({"orderNo": "E1", "status": "REJECTED"}))
    assert len(seen) == 1
    assert seen[0]["status"] == OrderStatus.REJECTED


def test_callback_exception_is_contained():
    def boom(_snap):
        raise RuntimeError("callback explosion")

    feed = DhanOrderUpdateFeed(client_id="c", access_token="t", on_update=boom)
    feed.inject_update(_alert({"orderNo": "F1", "status": "TRADED"}))
    assert feed.snapshot("F1") is not None  # dispatch survived the callback


# ---------------------------------------------------------------------------
# Adapter orchestration — WS first, REST fallback unchanged
# ---------------------------------------------------------------------------


class _StubFeed:
    """Duck-typed feed double: healthy flag + scripted snapshots."""

    def __init__(self, healthy=True, snaps=None, wake_after=None):
        self._healthy = healthy
        self._snaps = dict(snaps or {})
        self._calls = 0
        self._wake_after = wake_after
        self.wait_calls = 0

    @property
    def healthy(self):
        return self._healthy

    def snapshot(self, order_id):
        self._calls += 1
        if self._wake_after is not None and self._calls > self._wake_after:
            return self._snaps.get(order_id)
        return self._snaps.get(order_id) if self._wake_after is None else None

    def wait_for_update(self, order_id, timeout):
        self.wait_calls += 1
        return self._wake_after is not None


def _make_adapter(mock_broker, *, storage=None):
    adapter = DhanBrokerAdapter.__new__(DhanBrokerAdapter)
    adapter._broker = mock_broker
    adapter._order_poll_interval = 0.01
    adapter._order_poll_timeout = 2.0
    adapter._config = None
    adapter._executing_signal_ids = set()
    adapter._executing_lock = threading.Lock()
    adapter._storage = storage
    adapter._order_feed_enabled = True
    adapter._order_feed = None
    adapter._order_feed_lock = threading.Lock()
    adapter._broker_order_to_signal = {}
    return adapter


def test_poll_uses_ws_snapshot_without_rest_call():
    broker = MagicMock()
    adapter = _make_adapter(broker)
    adapter._order_feed = _StubFeed(
        snaps={"W1": {"status": OrderStatus.FILLED, "quantity": 65,
                      "filled_quantity": 65, "average_fill_price": 101.5,
                      "symbol": "NIFTY", "timestamp": "t", "raw_status": "TRADED"}}
    )

    order = adapter._poll_for_terminal_status("W1", timeout=2.0)

    assert order is not None
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == pytest.approx(65.0)
    assert order.average_fill_price == pytest.approx(101.5)
    broker.get_order_status.assert_not_called()


def test_poll_wakes_mid_wait_on_ws_update():
    broker = MagicMock()
    adapter = _make_adapter(broker)
    adapter._order_feed = _StubFeed(
        snaps={"W2": {"status": OrderStatus.REJECTED, "quantity": 65,
                      "filled_quantity": 0, "average_fill_price": 0,
                      "symbol": "NIFTY", "timestamp": "t", "raw_status": "REJECTED"}},
        wake_after=1,  # first snapshot empty, wake, second snapshot terminal
    )

    order = adapter._poll_for_terminal_status("W2", timeout=2.0)

    assert order is not None
    assert order.status == OrderStatus.REJECTED
    broker.get_order_status.assert_not_called()


def test_poll_falls_back_to_rest_when_feed_unhealthy():
    broker = MagicMock()
    broker.get_order_status.return_value = SimpleNamespace(
        status=OrderStatus.FILLED, quantity=4, filled_quantity=4,
        average_fill_price=100.0, timestamp="t",
    )
    adapter = _make_adapter(broker)
    adapter._order_feed = _StubFeed(healthy=False)

    order = adapter._poll_for_terminal_status("W3", timeout=2.0)

    assert order is not None
    assert order.status == OrderStatus.FILLED
    broker.get_order_status.assert_called()


def test_poll_falls_back_to_rest_when_feed_disabled():
    broker = MagicMock()
    broker.get_order_status.return_value = SimpleNamespace(
        status=OrderStatus.FILLED, quantity=4, filled_quantity=4,
        average_fill_price=100.0, timestamp="t",
    )
    adapter = _make_adapter(broker)
    adapter._order_feed_enabled = False

    order = adapter._poll_for_terminal_status("W4", timeout=2.0)

    assert order is not None
    broker.get_order_status.assert_called()


def test_ws_miss_completes_via_rest_within_remaining_budget():
    """WS gives nothing before the deadline: REST finishes the job."""
    broker = MagicMock()
    broker.get_order_status.return_value = SimpleNamespace(
        status=OrderStatus.CANCELLED, quantity=4, filled_quantity=0,
        average_fill_price=0.0, timestamp="t",
    )
    adapter = _make_adapter(broker)
    adapter._order_feed = _StubFeed(snaps={})  # healthy but silent

    order = adapter._poll_for_terminal_status("W5", timeout=0.5)

    assert order is not None
    assert order.status == OrderStatus.CANCELLED
    broker.get_order_status.assert_called()


# ---------------------------------------------------------------------------
# WS callback -> durable order persistence
# ---------------------------------------------------------------------------


class _RecordingStorage:
    def __init__(self):
        self.updates = []

    def update_order_status(self, order_id, status, **kw):
        self.updates.append((order_id, status, kw))


def test_ws_fill_persists_durable_row():
    adapter = _make_adapter(MagicMock(), storage=_RecordingStorage())
    adapter._broker_order_to_signal["BRK-9"] = "sig-9"

    adapter._on_order_feed_update({
        "order_id": "BRK-9", "status": OrderStatus.FILLED, "raw_status": "TRADED",
        "quantity": 65.0, "filled_quantity": 65.0, "average_fill_price": 100.25,
        "symbol": "N", "timestamp": "t",
    })

    updates = adapter._storage.updates
    assert len(updates) == 1
    order_id, status, kw = updates[0]
    assert order_id == "sig-9"
    assert status == "FILLED"
    assert kw["filled_quantity"] == pytest.approx(65.0)
    assert kw["avg_fill_price"] == pytest.approx(100.25)


def test_ws_rejection_persists_durable_row():
    adapter = _make_adapter(MagicMock(), storage=_RecordingStorage())
    adapter._broker_order_to_signal["BRK-8"] = "sig-8"

    adapter._on_order_feed_update({
        "order_id": "BRK-8", "status": OrderStatus.REJECTED, "raw_status": "REJECTED",
        "quantity": 65.0, "filled_quantity": 0.0, "average_fill_price": 0.0,
        "symbol": "N", "timestamp": "t",
    })

    assert adapter._storage.updates == [
        ("sig-8", "REJECTED", {"filled_quantity": None, "avg_fill_price": None})
    ]


def test_ws_non_terminal_transition_skips_persistence():
    """In-flight transitions must leave the durable row in-flight for restart
    reconciliation — only terminal states are persisted."""
    adapter = _make_adapter(MagicMock(), storage=_RecordingStorage())
    adapter._broker_order_to_signal["BRK-7"] = "sig-7"

    adapter._on_order_feed_update({
        "order_id": "BRK-7", "status": OrderStatus.OPEN, "raw_status": "PART_TRADED",
        "quantity": 65.0, "filled_quantity": 30.0, "average_fill_price": 100.0,
        "symbol": "N", "timestamp": "t",
    })

    assert adapter._storage.updates == []


def test_ws_update_for_unknown_order_is_ignored():
    adapter = _make_adapter(MagicMock(), storage=_RecordingStorage())

    adapter._on_order_feed_update({
        "order_id": "UNKNOWN", "status": OrderStatus.FILLED, "raw_status": "TRADED",
        "quantity": 65.0, "filled_quantity": 65.0, "average_fill_price": 100.0,
        "symbol": "N", "timestamp": "t",
    })

    assert adapter._storage.updates == []


def test_ws_persistence_failure_is_contained():
    class _ExplodingStorage:
        def update_order_status(self, *a, **kw):
            raise RuntimeError("db down")

    adapter = _make_adapter(MagicMock(), storage=_ExplodingStorage())
    adapter._broker_order_to_signal["BRK-6"] = "sig-6"

    adapter._on_order_feed_update({
        "order_id": "BRK-6", "status": OrderStatus.FILLED, "raw_status": "TRADED",
        "quantity": 65.0, "filled_quantity": 65.0, "average_fill_price": 100.0,
        "symbol": "N", "timestamp": "t",
    })  # must not raise
