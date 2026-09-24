from datetime import datetime, timezone
from decimal import Decimal

import pytest

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.application.oms.protective_order_service import ProtectiveOrderService
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Fill

CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s")


def test_protection_prepare_crash_rolls_back_event_and_projection(tmp_path):
    connection = create_database(tmp_path / "oms.sqlite3")

    def fail(stage):
        if stage == "before_commit":
            raise RuntimeError("simulated protection crash")

    service = ProtectiveOrderService(
        connection=connection,
        journal=SqliteExecutionJournal(connection, failure_hook=fail),
    )
    fill = Fill("f", "i", CONTRACT, 65, Decimal("100"), Decimal("0"), datetime.now(timezone.utc))
    with pytest.raises(RuntimeError, match="simulated protection crash"):
        service.ensure_for_fill(fill, stop_price=Decimal("95"))
    assert connection.execute("SELECT COUNT(*) FROM protection_orders").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 0
