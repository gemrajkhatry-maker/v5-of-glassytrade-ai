"""Versioned SQLite migration chain for execution state."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from glassytrade.adapters.persistence.sqlite.schema import (
    EXECUTION_CORE,
    PROJECTIONS,
    RECONCILIATION,
    SCHEMA_MIGRATIONS,
)


class MigrationError(RuntimeError):
    """Raised when the database migration history is not trusted."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


MIGRATIONS = (
    Migration(1, "0001_execution_core", EXECUTION_CORE),
    Migration(2, "0002_projections", PROJECTIONS),
    Migration(3, "0003_reconciliation", RECONCILIATION),
)


def _statements(sql: str) -> tuple[str, ...]:
    return tuple(statement.strip() for statement in sql.split(";") if statement.strip())


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(SCHEMA_MIGRATIONS)
    known = {migration.version: migration for migration in MIGRATIONS}
    applied = {
        int(row["version"]): row
        for row in connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        )
    }
    unknown = set(applied) - set(known)
    if unknown:
        raise MigrationError(f"unknown schema migration version(s): {sorted(unknown)}")
    for version, row in applied.items():
        migration = known[version]
        if row["checksum"] != migration.checksum:
            raise MigrationError(f"migration checksum mismatch for version {version}")
        if row["name"] != migration.name:
            raise MigrationError(f"migration name mismatch for version {version}")

    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _statements(migration.sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def create_database(path: Path | str) -> sqlite3.Connection:
    """Open one SQLite database and apply the trusted migration chain."""

    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database_path,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    apply_migrations(connection)
    return connection


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)
