"""Fail-closed SQLite WAL adapter bridge (backend/app/infrastructure/storage/sqlite_storage.py).

Alias/bridge for database.py to satisfy target v6.0 layout.
"""

from __future__ import annotations

from backend.app.infrastructure.storage.database import (
    DataIntegrityError,
    SQLiteStorageAdapter,
)

__all__ = [
    "DataIntegrityError",
    "SQLiteStorageAdapter",
]
