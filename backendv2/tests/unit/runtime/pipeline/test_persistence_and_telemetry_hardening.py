"""Hardening tests for persistence buffering and telemetry ring metrics."""

from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.runtime.pipeline import telemetry as telemetry_module
from app.runtime.pipeline.events import Tick
from app.runtime.pipeline.persistence import EventPersistence
from app.runtime.pipeline.telemetry import TelemetryPipeline


def _tick(idx: int) -> Tick:
    return Tick(
        symbol="BANKNIFTY",
        price=45000.0 + idx,
        volume=1.0,
        timestamp=float(idx),
        bid=45000.0 + idx,
        ask=45000.0 + idx,
        bid_volume=0.0,
        ask_volume=0.0,
    )


def test_persistence_buffer_drops_oldest_when_limit_exceeded() -> None:
    storage = SQLiteStorageAdapter()
    storage.init(":memory:")
    persistence = EventPersistence(storage=storage, batch_size=64, buffer_limit=3)

    for idx in range(5):
        persistence.process(_tick(idx))

    snapshot = persistence.snapshot()
    assert snapshot["dropped_events"] == 2
    assert snapshot["buffer_limit"] == 3
    assert len(snapshot["buffer"]) == 3

    persistence.flush()
    cursor = storage._conn.execute("SELECT COUNT(*) as count FROM ticks")
    assert cursor.fetchone()["count"] == 3

    restored = EventPersistence(storage=storage, batch_size=64, buffer_limit=3)
    restored.restore(snapshot)
    restored_snapshot = restored.snapshot()
    assert restored_snapshot["buffer_limit"] == 3
    assert len(restored_snapshot["buffer"]) == 3


def test_telemetry_ring_keeps_latest_samples(monkeypatch) -> None:
    telemetry = TelemetryPipeline()
    clock = {"tick": 0}

    def _fake_clock() -> int:
        clock["tick"] += 1_000
        return clock["tick"]

    monkeypatch.setattr(telemetry_module.time, "perf_counter_ns", _fake_clock)

    for span_id in range(2200):
        telemetry.start_span(span_id)
        telemetry.end_span("SessionRuntime", span_id)

    snapshot = telemetry.snapshot()
    assert snapshot["latency_ns"]["SessionRuntime"]["count"] == 2048
    assert snapshot["latency_ns"]["SessionRuntime"]["p95"] > 0


def test_persistence_records_flush_failure_without_dropping_buffer() -> None:
    storage = SQLiteStorageAdapter()
    storage.init(":memory:")
    storage._conn.close()

    persistence = EventPersistence(storage=storage, batch_size=1, buffer_limit=4)
    persistence.process(_tick(0))

    snapshot = persistence.snapshot()
    assert snapshot["flush_failures"] == 1
    assert snapshot["flush_count"] == 0
    assert len(snapshot["buffer"]) == 1

    restored = EventPersistence(storage=storage, batch_size=1, buffer_limit=4)
    restored.restore(snapshot)
    restored_snapshot = restored.snapshot()
    assert restored_snapshot["flush_failures"] == 1
    assert len(restored_snapshot["buffer"]) == 1
