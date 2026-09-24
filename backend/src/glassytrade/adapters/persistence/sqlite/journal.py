"""Append-only SQLite execution journal."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from glassytrade.domain.ledger.events import LedgerEvent

_DEFAULT_SECRET = b"glassytrade-execution-journal-v1"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class JournalError(RuntimeError):
    """Base error for durable journal operations."""


class SequenceError(JournalError):
    """Raised when an aggregate event sequence is not append-only."""


class JournalIntegrityError(JournalError):
    """Raised when persisted event bytes do not match their checksum."""


class SqliteExecutionJournal:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        secret: bytes | str = _DEFAULT_SECRET,
        failure_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.connection = connection
        self.secret = secret.encode("utf-8") if isinstance(secret, str) else secret
        self.failure_hook = failure_hook

    def _hook(self, stage: str) -> None:
        if self.failure_hook is not None:
            self.failure_hook(stage)

    @staticmethod
    def _payload_json(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)

    def _checksum(self, event: LedgerEvent) -> str:
        body = "|".join(
            (
                event.event_id,
                event.aggregate_id,
                str(event.aggregate_sequence),
                event.event_type,
                str(event.schema_version),
                event.occurred_at.isoformat(),
                event.received_at.isoformat(),
                event.correlation_id,
                event.causation_id or "",
                self._payload_json(event.payload),
            )
        ).encode("utf-8")
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def _validate(self, event: LedgerEvent) -> str:
        if event.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise JournalError(f"unsupported event schema version: {event.schema_version}")
        checksum = self._checksum(event)
        if event.checksum is not None and not hmac.compare_digest(event.checksum, checksum):
            raise JournalIntegrityError(f"event checksum mismatch: {event.event_id}")
        return checksum

    def _insert_validated(self, event: LedgerEvent, checksum: str) -> int:
        existing = self.connection.execute(
            "SELECT sequence FROM execution_events WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()
        if existing is not None:
            raise JournalError(f"duplicate event_id: {event.event_id}")
        previous = self.connection.execute(
            "SELECT MAX(aggregate_sequence) FROM execution_events WHERE aggregate_id = ?",
            (event.aggregate_id,),
        ).fetchone()[0]
        expected = int(previous or 0) + 1
        if event.aggregate_sequence != expected:
            raise SequenceError(
                f"aggregate sequence {event.aggregate_sequence} is not next ({expected})"
            )
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute(
            "INSERT INTO execution_events(" 
            "event_id, aggregate_id, aggregate_sequence, event_type, schema_version, "
            "occurred_at, received_at, correlation_id, causation_id, payload_json, "
            "checksum, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.aggregate_id,
                event.aggregate_sequence,
                event.event_type,
                event.schema_version,
                event.occurred_at.isoformat(),
                event.received_at.isoformat(),
                event.correlation_id,
                event.causation_id,
                self._payload_json(event.payload),
                checksum,
                created_at,
            ),
        )
        self._hook("after_event_append")
        sequence = int(cursor.lastrowid)
        self.connection.execute(
            "INSERT INTO outbox(event_sequence, event_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                sequence,
                event.event_type,
                self._payload_json(event.payload),
                created_at,
            ),
        )
        self._hook("before_outbox_publish")
        return sequence

    def append_in_transaction(self, event: LedgerEvent) -> int:
        """Append while the caller owns the SQLite transaction."""

        checksum = self._validate(event)
        return self._insert_validated(event, checksum)

    def before_commit(self) -> None:
        """Run the configured pre-commit failure boundary."""

        self._hook("before_commit")

    def append(self, event: LedgerEvent) -> None:
        checksum = self._validate(event)
        transaction_started = False
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            transaction_started = True
            self._insert_validated(event, checksum)
            self._hook("before_commit")
            self.connection.execute("COMMIT")
            transaction_started = False
            self._hook("after_commit")
        except Exception:
            if transaction_started:
                self.connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LedgerEvent:
        return LedgerEvent(
            event_id=row["event_id"],
            aggregate_id=row["aggregate_id"],
            aggregate_sequence=int(row["aggregate_sequence"]),
            event_type=row["event_type"],
            schema_version=int(row["schema_version"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            received_at=datetime.fromisoformat(row["received_at"]),
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            payload=json.loads(row["payload_json"]),
            checksum=row["checksum"],
        )

    def read_after(self, sequence: int) -> tuple[LedgerEvent, ...]:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        rows = self.connection.execute(
            "SELECT * FROM execution_events WHERE sequence > ? ORDER BY sequence",
            (sequence,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def replay(self) -> tuple[LedgerEvent, ...]:
        return self.read_after(0)

    def verify(self) -> None:
        expected: dict[str, int] = {}
        for row in self.connection.execute(
            "SELECT * FROM execution_events ORDER BY sequence"
        ):
            event = self._from_row(row)
            actual = self._checksum(event)
            if not hmac.compare_digest(actual, row["checksum"]):
                raise JournalIntegrityError(f"event checksum mismatch: {event.event_id}")
            next_sequence = expected.get(event.aggregate_id, 0) + 1
            if event.aggregate_sequence != next_sequence:
                raise SequenceError(
                    f"aggregate sequence gap for {event.aggregate_id}: "
                    f"expected {next_sequence}, got {event.aggregate_sequence}"
                )
            expected[event.aggregate_id] = event.aggregate_sequence

    def outbox_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])
