from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.adapters.persistence.sqlite.projections import SqliteProjector
from glassytrade.domain.ledger.events import LedgerEvent

IST = ZoneInfo("Asia/Kolkata")


def lifecycle_events() -> tuple[LedgerEvent, ...]:
    occurred = datetime(2026, 9, 24, 10, 0, tzinfo=IST)
    return (
        LedgerEvent(
            event_id="evt-intent",
            aggregate_id="intent-1",
            aggregate_sequence=1,
            event_type="OrderIntentRecorded",
            schema_version=1,
            occurred_at=occurred,
            received_at=occurred,
            correlation_id="corr-1",
            causation_id=None,
            payload={
                "intent_id": "intent-1",
                "idempotency_key": "idem-1",
                "contract_id": "NIFTY 27 AUG 25000 CALL",
                "side": "BUY",
                "requested_quantity": 2,
            },
        ),
        LedgerEvent(
            event_id="evt-fill",
            aggregate_id="intent-1",
            aggregate_sequence=2,
            event_type="FillRecorded",
            schema_version=1,
            occurred_at=occurred,
            received_at=occurred,
            correlation_id="corr-1",
            causation_id="evt-intent",
            payload={
                "fill_id": "fill-1",
                "intent_id": "intent-1",
                "contract_id": "NIFTY 27 AUG 25000 CALL",
                "quantity": 1,
                "price": "100.05",
            },
        ),
    )


def test_projection_rebuild_is_replayable_without_deleting_lifecycle_events(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")
    journal = SqliteExecutionJournal(connection)
    for item in lifecycle_events():
        journal.append(item)
    projector = SqliteProjector(connection)

    projector.rebuild()
    assert projector.order_intent("intent-1")["requested_quantity"] == 2
    assert projector.position_rows()[0]["signed_quantity"] == 1
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 2

    projector.rebuild()
    assert projector.order_intent("intent-1")["requested_quantity"] == 2
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 2


def test_projection_failure_never_mutates_lifecycle_events(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")
    journal = SqliteExecutionJournal(connection)
    for item in lifecycle_events():
        journal.append(item)

    def fail_after_projection(stage: str) -> None:
        if stage == "after_projection":
            raise RuntimeError("simulated projector crash")

    projector = SqliteProjector(connection, failure_hook=fail_after_projection)
    with pytest.raises(RuntimeError, match="simulated projector crash"):
        projector.rebuild()
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
