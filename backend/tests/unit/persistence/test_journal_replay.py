from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from glassytrade.adapters.persistence.sqlite.journal import (
    JournalIntegrityError,
    SequenceError,
    SqliteExecutionJournal,
)
from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.domain.ledger.events import LedgerEvent

IST = ZoneInfo("Asia/Kolkata")


def event(sequence: int = 1, event_id: str = "evt-1") -> LedgerEvent:
    timestamp = datetime(2026, 9, 24, 10, 0, tzinfo=IST)
    return LedgerEvent(
        event_id=event_id,
        aggregate_id="intent-1",
        aggregate_sequence=sequence,
        event_type="IntentCreated",
        schema_version=1,
        occurred_at=timestamp,
        received_at=timestamp,
        correlation_id="corr-1",
        causation_id=None,
        payload={"intent_id": "intent-1", "sequence": sequence},
    )


def test_journal_replay_is_deterministic_and_read_after_is_ordered(tmp_path):
    journal = SqliteExecutionJournal(create_database(tmp_path / "oms.sqlite3"))
    journal.append(event(1, "evt-1"))
    journal.append(event(2, "evt-2"))

    first = journal.replay()
    second = journal.replay()
    assert first == second
    assert [item.event_id for item in first] == ["evt-1", "evt-2"]
    assert journal.read_after(1)[0].event_id == "evt-2"
    assert journal.outbox_count() == 2
    journal.verify()


def test_journal_rejects_duplicate_aggregate_sequence_and_event_id(tmp_path):
    journal = SqliteExecutionJournal(create_database(tmp_path / "oms.sqlite3"))
    journal.append(event(1, "evt-1"))
    with pytest.raises(SequenceError):
        journal.append(event(1, "evt-other"))
    with pytest.raises(Exception):
        journal.append(event(2, "evt-1"))


def test_journal_verifies_tampering(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")
    journal = SqliteExecutionJournal(connection)
    journal.append(event())
    connection.execute("UPDATE execution_events SET payload_json='{}'")
    connection.commit()
    with pytest.raises(JournalIntegrityError):
        journal.verify()


def test_failed_after_commit_hook_does_not_rollback_committed_event(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")

    def fail_after_commit(stage: str) -> None:
        if stage == "after_commit":
            raise RuntimeError("post-commit observer failed")

    journal = SqliteExecutionJournal(connection, failure_hook=fail_after_commit)
    with pytest.raises(RuntimeError, match="post-commit observer failed"):
        journal.append(event())
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1


def test_failed_precommit_hook_rolls_back_event_and_outbox(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")

    def fail_before_commit(stage: str) -> None:
        if stage == "before_commit":
            raise RuntimeError("simulated crash")

    journal = SqliteExecutionJournal(connection, failure_hook=fail_before_commit)
    with pytest.raises(RuntimeError, match="simulated crash"):
        journal.append(event())
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
