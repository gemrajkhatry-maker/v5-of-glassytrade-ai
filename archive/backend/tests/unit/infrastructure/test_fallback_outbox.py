from __future__ import annotations

from app.domain.ops.self_healing import DBFallbackBuffer
from app.infrastructure.storage.database import SQLiteStorageAdapter


def test_fallback_outbox_survives_adapter_restart(tmp_path):
    db_path = str(tmp_path / "fallback.db")
    first = SQLiteStorageAdapter(db_path=db_path)
    buffer = DBFallbackBuffer(persistence=first)
    buffer.buffer_write("save_trade", {"position_id": "T1", "symbol": "NIFTY"})
    first.close()

    second = SQLiteStorageAdapter(db_path=db_path)
    restored = DBFallbackBuffer(persistence=second)
    assert restored.buffer_size == 1

    writes: list[dict] = []
    second.save_trade = lambda payload: writes.append(payload)
    assert restored.try_flush(second) == 1
    assert writes == [{"position_id": "T1", "symbol": "NIFTY"}]
    assert second.load_fallback_writes() == []
    second.close()


def test_fallback_ack_failure_survives_restart_without_duplicate_trade(tmp_path):
    db_path = str(tmp_path / "ack-restart.db")
    payload = {
        "position_id": "committed-once",
        "symbol": "NIFTY",
        "side": "LONG",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "size": 1.0,
        "pnl": 10.0,
    }
    first = SQLiteStorageAdapter(db_path=db_path)
    buffer = DBFallbackBuffer(persistence=first)
    buffer.buffer_write("save_trade", payload)

    original_delete = first.delete_fallback_write_by_retry_id

    def fail_ack(retry_id):
        raise RuntimeError("process interrupted after original commit")

    first.delete_fallback_write_by_retry_id = fail_ack
    assert buffer.try_flush(first) == 0
    assert len(first.query_trades()) == 1
    first.close()

    second = SQLiteStorageAdapter(db_path=db_path)
    restored = DBFallbackBuffer(persistence=second)
    assert restored.buffer_size == 1
    assert restored.try_flush(second) == 1
    assert len(second.query_trades()) == 1
    assert second.load_fallback_writes() == []
    # Keep the original method referenced so this test documents the real ack
    # boundary rather than accidentally relying on a missing adapter API.
    assert callable(original_delete)
    second.close()


def test_fallback_outbox_keeps_fifo_when_first_write_fails(tmp_path):
    db_path = str(tmp_path / "fifo.db")
    storage = SQLiteStorageAdapter(db_path=db_path)
    buffer = DBFallbackBuffer(persistence=storage)
    buffer.buffer_write("save_trade", {"position_id": "first"})
    buffer.buffer_write("save_trade", {"position_id": "second"})

    calls: list[str] = []
    original = storage.save_trade
    attempts = {"count": 0}

    def fail_once(payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("offline")
        calls.append(payload["position_id"])
        original(payload)

    storage.save_trade = fail_once
    assert buffer.try_flush(storage) == 0
    assert buffer.buffer_size == 2
    assert calls == []
    assert len(storage.load_fallback_writes()) == 2

    assert buffer.try_flush(storage) == 2
    assert calls == ["first", "second"]
    assert storage.load_fallback_writes() == []
    storage.close()
