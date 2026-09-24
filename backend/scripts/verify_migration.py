"""Verify copied legacy table counts without opening the source for writes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerificationReport:
    verified: bool
    differences: tuple[str, ...]


def verify_migration(source: Path, target: Path) -> VerificationReport:
    source_connection = sqlite3.connect(f"file:{Path(source).resolve()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(f"file:{Path(target).resolve()}?mode=ro", uri=True)
    differences: list[str] = []
    try:
        tables = [
            row[0]
            for row in source_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            source_count = source_connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
            target_table = f"legacy_{table}"
            exists = target_connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                (target_table,),
            ).fetchone()
            if exists is None:
                differences.append(f"missing:{table}")
                continue
            target_count = target_connection.execute(
                f'SELECT COUNT(*) FROM "{target_table}"'
            ).fetchone()[0]
            if source_count != target_count:
                differences.append(f"count:{table}")
    finally:
        source_connection.close()
        target_connection.close()
    return VerificationReport(not differences, tuple(differences))
