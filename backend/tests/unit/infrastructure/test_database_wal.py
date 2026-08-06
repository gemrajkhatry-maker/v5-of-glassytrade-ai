"""Tests for SQLite persistence hardening (B-39/B-40).

Verifies:
- WAL journal mode is enabled at connection init.
- synchronous=NORMAL and busy_timeout are configured.
- The ticks(symbol, time) index exists after init.
"""

from __future__ import annotations

import pytest

from app.infrastructure.storage.database import SQLiteStorageAdapter


@pytest.fixture
def adapter(tmp_path):
    db_path = str(tmp_path / "test.db")
    a = SQLiteStorageAdapter(db_path=db_path)
    yield a
    a.close()


class TestDatabasePragmas:

    def test_journal_mode_is_wal(self, adapter):
        row = adapter._conn.execute("PRAGMA journal_mode").fetchone()
        assert row is not None
        assert str(row[0]).lower() == "wal"

    def test_synchronous_is_normal(self, adapter):
        row = adapter._conn.execute("PRAGMA synchronous").fetchone()
        assert row is not None
        assert int(row[0]) == 1  # 1 == NORMAL

    def test_busy_timeout_is_configured(self, adapter):
        row = adapter._conn.execute("PRAGMA busy_timeout").fetchone()
        assert row is not None
        assert int(row[0]) > 0


class TestTicksIndex:

    def test_ticks_symbol_time_index_exists(self, adapter):
        indexes = adapter._conn.execute("PRAGMA index_list('ticks')").fetchall()
        names = [str(r["name"]) for r in indexes]
        assert "idx_ticks_symbol_time" in names

    def test_ticks_index_in_sqlite_master(self, adapter):
        row = adapter._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_ticks_symbol_time' AND tbl_name='ticks'"
        ).fetchone()
        assert row is not None
        assert "symbol" in row["sql"]
        assert "time" in row["sql"]

    def test_ticks_index_is_unique(self, adapter):
        indexes = adapter._conn.execute("PRAGMA index_list('ticks')").fetchall()
        target = next(r for r in indexes if r["name"] == "idx_ticks_symbol_time")
        assert int(target["unique"]) == 1
