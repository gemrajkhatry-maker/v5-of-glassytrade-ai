import pytest

from glassytrade.adapters.persistence.sqlite.migrations import (
    MigrationError,
    create_database,
)


def test_migration_creates_execution_tables(tmp_path):
    db = create_database(tmp_path / "oms.sqlite3")
    names = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "execution_events",
        "outbox",
        "order_intents",
        "order_attempts",
        "fills",
        "risk_reservations",
        "positions",
        "protection_orders",
        "reconciliation_cases",
        "schema_migrations",
    } <= names
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 3
    db.close()


def test_migration_rejects_tampered_migration_checksum(tmp_path):
    path = tmp_path / "oms.sqlite3"
    db = create_database(path)
    db.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=1")
    db.commit()
    db.close()

    with pytest.raises(MigrationError, match="checksum"):
        create_database(path)
