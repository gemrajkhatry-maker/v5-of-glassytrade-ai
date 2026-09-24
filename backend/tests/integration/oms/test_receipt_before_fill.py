from datetime import datetime, timezone
from decimal import Decimal

from glassytrade.application.oms.command_service import OmsCommandService
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Fill


def test_duplicate_receipts_produce_one_fill_event(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    service = OmsCommandService(create_database(tmp_path / "oms.sqlite3"))
    fill = Fill(
        fill_id="fill-1",
        intent_id="intent-1",
        contract_id=ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s"),
        quantity=1,
        price=Decimal("100"),
        fees=Decimal("0"),
        filled_at=datetime.now(timezone.utc),
    )
    assert service.ingest_receipt(fill).accepted is True
    assert service.ingest_receipt(fill).accepted is False
    assert sum(event.event_type == "FillRecorded" for event in service.journal.replay()) == 1
