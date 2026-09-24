"""Transactional repository boundary for execution persistence."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Protocol

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.domain.ledger.events import LedgerEvent


class ExecutionTransaction(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor: ...


class ExecutionRepository(Protocol):
    def transaction(self): ...


class SqliteExecutionRepository:
    def __init__(self, connection: sqlite3.Connection, *, secret: bytes | str | None = None) -> None:
        self.connection = connection
        self.journal = SqliteExecutionJournal(connection, secret=secret) if secret is not None else SqliteExecutionJournal(connection)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def append(self, event: LedgerEvent) -> None:
        self.journal.append(event)
