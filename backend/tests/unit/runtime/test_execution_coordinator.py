from decimal import Decimal

from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.application.oms.command_service import OmsCommandService
from glassytrade.application.runtime.execution_coordinator import (
    ExecutionCoordinator,
    SubmitEntryCommand,
)
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.strategy.intent import EntryIntent


def entry_intent() -> EntryIntent:
    return EntryIntent(
        intent_id="intent-1",
        contract_id=ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s"),
        side="BUY",
        desired_quantity=1,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
        setup="test",
    )


def test_coordinator_creates_durable_intent_only_through_oms(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")
    oms = OmsCommandService(connection)
    coordinator = ExecutionCoordinator(oms, account_id="paper-main")
    outcome = coordinator.execute(SubmitEntryCommand(entry_intent()))
    assert outcome.status == "accepted"
    assert connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 1
    assert coordinator.mutation_count == 1


def test_coordinator_replays_same_command_idempotently(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")
    coordinator = ExecutionCoordinator(OmsCommandService(connection), account_id="paper-main")
    command = SubmitEntryCommand(entry_intent())
    first = coordinator.execute(command)
    second = coordinator.execute(command)
    assert first.status == second.status == "accepted"
    assert coordinator.mutation_count == 1
