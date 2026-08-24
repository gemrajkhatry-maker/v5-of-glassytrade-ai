from __future__ import annotations

import threading

from app.domain.ops.self_healing import DBFallbackBuffer
from app.infrastructure.storage.database import SQLiteStorageAdapter


class _UnavailableOutbox:
    def __init__(self, spool_path: str) -> None:
        self._spool_path = spool_path

    def fallback_spool_path(self) -> str:
        return self._spool_path

    def enqueue_fallback_write(self, *_args, **_kwargs):
        raise OSError("sqlite unavailable")

    def load_fallback_writes(self):
        raise OSError("sqlite unavailable")

    def delete_fallback_write(self, *_args, **_kwargs):
        raise AssertionError("SQLite outbox should not be acknowledged while unavailable")


def test_malformed_spool_record_is_quarantined_without_blocking_valid_records(tmp_path):
    spool_path = tmp_path / "recover.jsonl"
    spool_path.write_text(
        '{"type":"write","retry_id":"ok","key":"save_trade","data":{"position_id":"valid"}}\n'
        '{not-json}\n',
        encoding="utf-8",
    )
    buffer = DBFallbackBuffer(spool_path=str(spool_path))
    assert buffer.buffer_size == 1
    assert (tmp_path / "recover.jsonl.quarantine.jsonl").exists()


def test_local_spool_survives_sqlite_outage_and_restart(tmp_path):
    spool_path = str(tmp_path / "fallback.jsonl")
    unavailable = _UnavailableOutbox(spool_path)

    first = DBFallbackBuffer(persistence=unavailable)
    first.buffer_write("save_trade", {"position_id": "one"})
    first.buffer_write("save_trade", {"position_id": "two"})
    assert first.buffer_size == 2
    assert (tmp_path / "fallback.jsonl").exists()

    restarted = DBFallbackBuffer(persistence=unavailable)
    assert restarted.buffer_size == 2

    calls: list[str] = []

    class Storage:
        def save_trade(self, payload):
            calls.append(payload["position_id"])

    assert restarted.try_flush(Storage()) == 2
    assert calls == ["one", "two"]
    assert restarted.buffer_size == 0
    assert (tmp_path / "fallback.jsonl").read_text(encoding="utf-8") == ""


def test_local_spool_and_sqlite_outbox_same_retry_id_recover_once(tmp_path):
    spool_path = str(tmp_path / "dedupe.jsonl")

    class CommitThenRaise(_UnavailableOutbox):
        def __init__(self, path):
            super().__init__(path)
            self.payload = None

        def enqueue_fallback_write(self, _key, payload):
            self.payload = dict(payload)
            raise RuntimeError("committed, response lost")

        def load_fallback_writes(self):
            return [{"key": "save_trade", "data": dict(self.payload), "outbox_id": 7}]

        def delete_fallback_write(self, _item_id):
            return None

    persistence = CommitThenRaise(spool_path)
    buffer = DBFallbackBuffer(persistence=persistence)
    buffer.buffer_write("save_trade", {"position_id": "once"})

    recovered = DBFallbackBuffer(persistence=persistence)
    assert recovered.buffer_size == 1

    calls: list[str] = []

    class Storage:
        def save_trade(self, payload):
            calls.append(payload["position_id"])

    assert recovered.try_flush(Storage()) == 1
    assert calls == ["once"]


def test_sqlite_orphaned_outbox_row_is_removed_by_retry_id(tmp_path):
    storage = SQLiteStorageAdapter(db_path=str(tmp_path / "orphan.db"))
    payload = {"__db_fallback_id": "retry-1", "symbol": "NIFTY", "equity": 100}
    storage.enqueue_fallback_write("save_performance_snapshot", payload)
    assert len(storage.load_fallback_writes()) == 1
    storage.delete_fallback_write_by_retry_id("retry-1")
    assert storage.load_fallback_writes() == []
    storage.close()


def test_performance_snapshot_replay_with_same_retry_id_is_idempotent(tmp_path):
    storage = SQLiteStorageAdapter(db_path=str(tmp_path / "snapshot.db"))
    payload = {
        "__db_fallback_id": "snapshot-once",
        "symbol": "NIFTY",
        "equity": 100.0,
        "balance": 100.0,
        "open_pnl": 0.0,
        "open_positions": 0,
        "total_trades": 1,
        "win_rate": 1.0,
    }
    storage.save_performance_snapshot(payload)
    storage.save_performance_snapshot(payload)
    count = storage._conn.execute("SELECT COUNT(*) FROM performance_snapshots").fetchone()[0]
    assert count == 1
    storage.close()


def test_performance_snapshot_ack_failure_replays_once_after_restart(tmp_path):
    db_path = str(tmp_path / "snapshot-ack.db")
    first = SQLiteStorageAdapter(db_path=db_path)
    buffer = DBFallbackBuffer(persistence=first)
    buffer.buffer_write(
        "save_performance_snapshot",
        {
            "symbol": "NIFTY",
            "equity": 100.0,
            "balance": 100.0,
            "open_pnl": 0.0,
            "open_positions": 0,
            "total_trades": 1,
            "win_rate": 1.0,
        },
    )

    first.delete_fallback_write_by_retry_id = lambda _retry_id: (_ for _ in ()).throw(
        RuntimeError("ack failed after snapshot commit")
    )
    assert buffer.try_flush(first) == 0
    assert first._conn.execute("SELECT COUNT(*) FROM performance_snapshots").fetchone()[0] == 1
    first.close()

    second = SQLiteStorageAdapter(db_path=db_path)
    restored = DBFallbackBuffer(persistence=second)
    assert restored.try_flush(second) == 1
    assert second._conn.execute("SELECT COUNT(*) FROM performance_snapshots").fetchone()[0] == 1
    assert second.load_fallback_writes() == []
    second.close()


def test_concurrent_flushes_are_serialized_and_do_not_duplicate_writes(tmp_path):
    spool_path = str(tmp_path / "concurrent.jsonl")
    unavailable = _UnavailableOutbox(spool_path)
    buffer = DBFallbackBuffer(persistence=unavailable)
    buffer.buffer_write("save_trade", {"position_id": "one"})
    buffer.buffer_write("save_trade", {"position_id": "two"})

    calls: list[str] = []
    calls_lock = threading.Lock()

    class Storage:
        def save_trade(self, payload):
            with calls_lock:
                calls.append(payload["position_id"])

    results: list[int] = []

    def flush():
        results.append(buffer.try_flush(Storage()))

    threads = [threading.Thread(target=flush) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [0, 2]
    assert calls == ["one", "two"]
    assert buffer.buffer_size == 0
