from decimal import Decimal

import pytest

from glassytrade.application.oms.command_service import OmsCommandService
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


def test_prepare_entry_commits_reservation_intent_and_attempt_together(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    connection = create_database(tmp_path / "oms.sqlite3")
    service = OmsCommandService(connection)
    service.prepare_entry(entry_intent())
    assert connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM order_attempts").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM risk_reservations").fetchone()[0] == 1


def test_reservation_rejection_leaves_no_partial_order(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    connection = create_database(tmp_path / "oms.sqlite3")
    service = OmsCommandService(connection, max_reserved_risk=Decimal("0.01"))
    with pytest.raises(Exception):
        service.prepare_entry(entry_intent())
    assert connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0] == 0
