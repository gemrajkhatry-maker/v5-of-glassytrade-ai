"""B-5 partial: bridge/storage write failures latch PersistenceHealth.

EventBus isolates handler failures (log-only) — a PositionStorageBridge /
SQLite write failure must still latch a health flag, otherwise the event
store holds a position SQLite never saw and restart silently loses it.
"""

from __future__ import annotations

import logging

import pytest

from quant.decision.signal_builder import Signal
from quant.events import EventBus, PositionOpened
from quant.execution.order import Order, Position
from quant.persistence_bridge import PositionStorageBridge
from quant.persistence_boundary import PersistenceHealth


@pytest.fixture(autouse=True)
def _reset_bridge_latch():
    PersistenceHealth.bridge_write_degraded = False
    PersistenceHealth.bridge_write_failure = None
    yield
    PersistenceHealth.bridge_write_degraded = False
    PersistenceHealth.bridge_write_failure = None


def _position(pid: str = "p1") -> Position:
    sig = Signal(
        type="LONG", reason="t", entry=100.0, sl=90.0, tp=120.0,
        rr=2.0, model_label="Triple-A", symbol="S", timestamp="t0",
    )
    return Position(
        order=Order(sig, 4.0), open_price=100.0, open_time="t0",
        size=4.0, _id=pid,
    )


class _FailingStorage:
    def save_open_position(self, row: dict) -> None:
        raise OSError("sqlite disk full")


def test_bridge_storage_failure_latches_health_not_log_only(caplog):
    bus = EventBus()
    PositionStorageBridge(_FailingStorage()).attach(bus)

    with caplog.at_level(logging.ERROR, logger="quant.events"):
        bus.publish(PositionOpened(symbol="S", time="t0", position=_position()))

    assert PersistenceHealth.bridge_write_degraded is True
    assert isinstance(PersistenceHealth.bridge_write_failure, OSError)
    bridge_logs = [r for r in caplog.records if r.name == "quant.events"]
    assert bridge_logs, "bridge failure must be logged"
    assert any(r.exc_info for r in bridge_logs), "latch must log with exc_info"


def test_non_bridge_handler_failure_does_not_latch(caplog):
    bus = EventBus()

    def boom(event):
        raise RuntimeError("ui exploded")

    bus.subscribe(PositionOpened, boom)

    with caplog.at_level(logging.ERROR, logger="quant.events"):
        bus.publish(PositionOpened(symbol="S", time="t0", position=_position()))

    assert PersistenceHealth.bridge_write_degraded is False
    assert PersistenceHealth.bridge_write_failure is None


def test_successful_bridge_write_does_not_latch():
    class _OkStorage:
        def __init__(self):
            self.rows = []

        def save_open_position(self, row: dict) -> None:
            self.rows.append(row)

    bus = EventBus()
    PositionStorageBridge(_OkStorage()).attach(bus)
    bus.publish(PositionOpened(symbol="S", time="t0", position=_position()))

    assert PersistenceHealth.bridge_write_degraded is False
    assert PersistenceHealth.bridge_write_failure is None
