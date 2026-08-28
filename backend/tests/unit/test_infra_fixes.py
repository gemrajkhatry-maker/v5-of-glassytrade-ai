"""Tests for infrastructure fixes — memory caps, health endpoint, WAL, kv_store."""

import tempfile
import os


class TestKVStore:
    def test_kv_set_get_roundtrip(self):
        from app.infrastructure.storage.database import SQLiteStorageAdapter
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = SQLiteStorageAdapter(db_path=db_path)
            storage.kv_set("test_key", "test_value")
            assert storage.kv_get("test_key") == "test_value"

    def test_kv_get_missing_returns_none(self):
        from app.infrastructure.storage.database import SQLiteStorageAdapter
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = SQLiteStorageAdapter(db_path=db_path)
            assert storage.kv_get("nonexistent") is None

    def test_kv_upsert(self):
        from app.infrastructure.storage.database import SQLiteStorageAdapter
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = SQLiteStorageAdapter(db_path=db_path)
            storage.kv_set("key", "v1")
            storage.kv_set("key", "v2")
            assert storage.kv_get("key") == "v2"


class TestWALCheckpoint:
    def test_wal_autocheckpoint_set(self):
        from app.infrastructure.storage.database import SQLiteStorageAdapter
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = SQLiteStorageAdapter(db_path=db_path)
            result = storage._conn.execute("PRAGMA wal_autocheckpoint").fetchone()
            assert result[0] == 500
