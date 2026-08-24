from __future__ import annotations

import sqlite3

from app.infrastructure.storage.database import SQLiteStorageAdapter


def test_legacy_outbox_rows_receive_stable_ids_and_malformed_payload_does_not_block_startup(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE fallback_outbox ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, write_key TEXT NOT NULL, "
        "payload TEXT NOT NULL, created_at TEXT DEFAULT '2026-01-01 09:00:00')"
    )
    conn.execute(
        "INSERT INTO fallback_outbox(write_key, payload) VALUES (?, ?)",
        ("save_trade", '{"position_id":"legacy"}'),
    )
    conn.execute(
        "INSERT INTO fallback_outbox(write_key, payload) VALUES (?, ?)",
        ("save_trade", "not-json"),
    )
    conn.commit()
    conn.close()

    storage = SQLiteStorageAdapter(db_path=db_path)
    rows = storage.load_fallback_writes()
    assert [row["retry_id"] for row in rows] == ["legacy-outbox-1"]
    assert rows[0]["data"]["position_id"] == "legacy"
    assert len(rows) == 1
    quarantine = storage._conn.execute(
        "SELECT source_id, write_key, payload FROM fallback_outbox_quarantine"
    ).fetchall()
    assert len(quarantine) == 1
    assert quarantine[0]["source_id"] == 2
    assert quarantine[0]["write_key"] == "save_trade"
    assert quarantine[0]["payload"] == "not-json"
    storage.close()


def test_duplicate_retry_ids_are_reduced_before_unique_index_creation(tmp_path):
    db_path = str(tmp_path / "duplicates.db")
    storage = SQLiteStorageAdapter(db_path=db_path)
    storage._conn.execute("DROP INDEX idx_fallback_retry_id")
    storage._conn.execute(
        "INSERT INTO fallback_outbox(retry_id, write_key, payload, created_at_epoch) "
        "VALUES ('same', 'save_trade', '{}', 1), ('same', 'save_trade', '{}', 2)"
    )
    storage._conn.commit()
    storage.close()

    reopened = SQLiteStorageAdapter(db_path=db_path)
    rows = reopened._conn.execute(
        "SELECT retry_id FROM fallback_outbox WHERE retry_id = 'same'"
    ).fetchall()
    assert len(rows) == 1
    reopened.close()
