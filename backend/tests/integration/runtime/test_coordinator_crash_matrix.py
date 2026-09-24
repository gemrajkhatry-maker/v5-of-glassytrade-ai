from decimal import Decimal

import pytest

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.application.oms.command_service import OmsCommandService
from glassytrade.application.runtime.execution_coordinator import ExecutionCoordinator, SubmitEntryCommand
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.strategy.intent import EntryIntent


def entry_intent():
    return EntryIntent(
        intent_id="entry-1",
        contract_id=ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "sec-1"),
        side="BUY",
        desired_quantity=1,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
        setup="test",
    )


@pytest.mark.parametrize("stage", ["after_event_append", "before_commit"])
def test_coordinator_crash_does_not_leave_partial_authority(tmp_path, stage):
    connection = create_database(tmp_path / "oms.sqlite3")

    def fail(seen):
        if seen == stage:
            raise RuntimeError("simulated coordinator crash")

    journal = SqliteExecutionJournal(connection, failure_hook=fail)
    oms = OmsCommandService(connection, journal=journal)
    coordinator = ExecutionCoordinator(oms, account_id="paper-main")
    outcome = coordinator.execute(SubmitEntryCommand(entry_intent()))
    assert outcome.status == "rejected"
    assert coordinator.mutation_count == 0
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 0
