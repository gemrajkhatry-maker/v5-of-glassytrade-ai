from decimal import Decimal

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.strategy.intent import EntryIntent


def entry_intent():
    return EntryIntent(
        intent_id="entry-1",
        contract_id=ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "sec-1"),
        side="BUY",
        desired_quantity=2,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
        setup="test-setup",
    )


def test_repeated_command_returns_same_internal_identity(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database
    from glassytrade.application.oms.command_service import OmsCommandService

    service = OmsCommandService(create_database(tmp_path / "oms.sqlite3"))
    first = service.prepare_entry(entry_intent())
    second = service.prepare_entry(entry_intent())
    assert first.intent.intent_id == second.intent.intent_id
    assert first.attempt.attempt_id == second.attempt.attempt_id
    assert service.attempt_count() == 1
