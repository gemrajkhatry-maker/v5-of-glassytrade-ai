from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from glassytrade.application.oms.command_service import (
    IdempotencyConflict,
    OmsCommandService,
    ReconciliationRequired,
)
from glassytrade.application.ports.broker import BrokerPlaceRequest
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Fill
from glassytrade.domain.strategy.intent import EntryIntent

CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "sec-1")


def entry_intent(intent_id: str = "entry-1", key: str = "idem-1") -> EntryIntent:
    return EntryIntent(
        intent_id=intent_id,
        contract_id=CONTRACT,
        side="BUY",
        desired_quantity=2,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
        setup="test-setup",
        evidence_ids=("evidence-1",),
        mode="paper",
    )


class FakeBroker:
    def __init__(self):
        self.unknown_attempt_ids = set()
        self.requests = []

    def force_unknown(self, attempt_id: str) -> None:
        self.unknown_attempt_ids.add(attempt_id)

    def place_order(self, request: BrokerPlaceRequest):
        self.requests.append(request)
        return request


def test_same_idempotency_key_and_payload_returns_one_prepared_order(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    service = OmsCommandService(create_database(tmp_path / "oms.sqlite3"))
    first = service.prepare_entry(entry_intent())
    second = service.prepare_entry(entry_intent())
    assert second.intent.intent_id == first.intent.intent_id
    assert service.attempt_count() == 1


def test_same_idempotency_key_with_different_payload_is_rejected(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    service = OmsCommandService(create_database(tmp_path / "oms.sqlite3"))
    service.prepare_entry(entry_intent())
    with pytest.raises(IdempotencyConflict):
        service.prepare_entry(replace(entry_intent(), desired_quantity=3))


def test_unknown_attempt_never_dispatches_another_attempt(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    service = OmsCommandService(create_database(tmp_path / "oms.sqlite3"))
    prepared = service.prepare_entry(entry_intent())
    service.mark_attempt_unknown(prepared.attempt.attempt_id)
    with pytest.raises(ReconciliationRequired):
        service.claim_dispatch(prepared.attempt.attempt_id)


def test_risk_reservation_and_intent_commit_atomically(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    connection = create_database(tmp_path / "oms.sqlite3")
    service = OmsCommandService(connection, max_reserved_risk=Decimal("1"))
    with pytest.raises(Exception):
        service.prepare_entry(entry_intent())
    assert service.attempt_count() == 0
    assert service.intent_count() == 0


def test_receipt_is_recorded_before_actual_fill(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    service = OmsCommandService(create_database(tmp_path / "oms.sqlite3"))
    fill = Fill(
        fill_id="fill-1",
        intent_id="entry-1",
        contract_id=CONTRACT,
        quantity=1,
        price=Decimal("100"),
        fees=Decimal("0"),
        filled_at=datetime.now(timezone.utc),
    )
    first = service.ingest_receipt(fill)
    second = service.ingest_receipt(fill)
    assert first.accepted is True
    assert second.accepted is False
    event_types = [event.event_type for event in service.journal.replay()]
    assert event_types.index("BrokerReceiptRecorded") < event_types.index("FillRecorded")
