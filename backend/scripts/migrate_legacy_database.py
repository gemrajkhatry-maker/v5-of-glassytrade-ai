"""Copy legacy SQLite tables into an isolated target release database."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.domain.execution.types import MigrationManifest


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def migrate_database(source: Path, target: Path, release_id: str) -> MigrationManifest:
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        raise ValueError("source and target must be different databases")
    if not source.exists():
        raise FileNotFoundError(source)
    started = datetime.now(timezone.utc)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_connection = create_database(target)
    row_counts: dict[str, int] = {}
    try:
        tables = [
            row[0]
            for row in source_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            columns = [
                row[1]
                for row in source_connection.execute(f"PRAGMA table_info({_quote(table)})")
            ]
            target_table = f"legacy_{table}"
            column_sql = ", ".join(
                f"{_quote(column)} TEXT" for column in columns
            )
            target_connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_quote(target_table)} ({column_sql})"
            )
            rows = source_connection.execute(
                f"SELECT * FROM {_quote(table)}"
            ).fetchall()
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                names = ", ".join(_quote(column) for column in columns)
                target_connection.executemany(
                    f"INSERT INTO {_quote(target_table)} ({names}) VALUES ({placeholders})",
                    rows,
                )
            row_counts[table] = len(rows)
        target_connection.commit()
    finally:
        source_connection.close()
        target_connection.close()
    completed = datetime.now(timezone.utc)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    return MigrationManifest(
        release_id=release_id,
        source=str(source),
        target=str(target),
        checksum=checksum,
        started_at=started,
        completed_at=completed,
        row_counts=row_counts,
    )
