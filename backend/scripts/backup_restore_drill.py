"""SQLite online backup and semantic restore verification drill."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def restore_backup(source: Path, target: Path) -> None:
    source = Path(source)
    target = Path(target)
    if source.resolve() == target.resolve():
        raise ValueError("backup source and restore target must differ")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        source_connection.close()
        target_connection.close()


def semantic_projection_hash(path: Path) -> str:
    connection = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    digest = hashlib.sha256()
    try:
        tables = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        for table in tables:
            digest.update(table.encode())
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            digest.update(repr((columns, rows)).encode())
    finally:
        connection.close()
    return digest.hexdigest()
