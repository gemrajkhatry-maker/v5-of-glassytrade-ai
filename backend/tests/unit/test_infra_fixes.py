"""Tests for infrastructure fixes — memory caps, health endpoint, WAL, kv_store."""

import time
import tempfile
import os

from app.domain.fabio_ai.services.regime_detector import RegimeDetector


class TestFailedEntriesCapped:
    def test_capped_at_50(self):
        rd = RegimeDetector()
        for i in range(60):
            rd.record_failed_entry(level=100.0 + i * 0.1, direction="LONG", session_phase=1)
        assert len(rd._failed_entries) <= 50

    def test_keeps_newest(self):
        rd = RegimeDetector()
        for i in range(60):
            rd.record_failed_entry(level=float(i), direction="LONG", session_phase=1)
        # Last entry should be level 59
        assert rd._failed_entries[-1].level == 59.0


class TestLevelTouchesCapped:
    def test_capped_at_100(self):
        rd = RegimeDetector()
        # Insert 120 levels by calling record_level_approach at each
        base_time = time.time()
        for i in range(120):
            level = 100.0 + i * 0.5
            rd.record_level_approach(
                price=level, key_levels=[level], timestamp=base_time + i,
            )
        assert len(rd._level_touches) <= 100


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
