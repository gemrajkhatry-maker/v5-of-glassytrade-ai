from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.common.money import to_decimal
from glassytrade.domain.common.provenance import EvidenceQuality
from glassytrade.domain.execution.types import (
    AmbiguousOutcome,
    BrokerCapabilities,
    BrokerOrderSnapshot,
    ExecutionAttempt,
    ExecutionAttemptStatus,
    Fill,
    NotSent,
    OrderIntent,
    OrderSide,
    Readiness,
    ReadinessStatus,
    RiskReservation,
    RiskReservationStatus,
)
from glassytrade.domain.ledger.events import LedgerEvent
from glassytrade.domain.market_data.events import MarketDataEvent

IST = ZoneInfo("Asia/Kolkata")


def valid_contract() -> ContractId:
    return ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "sec-1")


def test_contract_id_is_immutable_and_validated():
    contract = valid_contract()
    assert contract.security_id == "sec-1"
    with pytest.raises(ValueError):
        ContractId("", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "1")
    with pytest.raises(FrozenInstanceError):
        contract.root = "BANKNIFTY"  # type: ignore[misc]


def test_money_and_market_data_event_use_explicit_types():
    event = MarketDataEvent(
        event_id="evt-1",
        contract_id=valid_contract(),
        exchange_timestamp=datetime(2026, 9, 24, 10, 0, tzinfo=IST),
        received_timestamp=datetime(2026, 9, 24, 10, 0, 1, tzinfo=IST),
        sequence_number=1,
        event_type="LTP",
        price=Decimal("100.05"),
        size=10,
        side=None,
        provenance=EvidenceQuality.PROXY,
    )
    assert event.provenance is EvidenceQuality.PROXY
    assert to_decimal("100.05") == Decimal("100.05")
    with pytest.raises(ValueError):
        MarketDataEvent(
            event_id="evt-2",
            contract_id=valid_contract(),
            exchange_timestamp=datetime(2026, 9, 24, 10, 0, tzinfo=IST),
            received_timestamp=datetime(2026, 9, 24, 10, 0, 1, tzinfo=IST),
            sequence_number=-1,
            event_type="LTP",
            price=Decimal("1"),
            size=1,
            side=None,
            provenance=EvidenceQuality.EXACT,
        )


def test_order_attempt_fill_and_reservation_keep_internal_identities_distinct():
    intent = OrderIntent(
        intent_id="intent-1",
        idempotency_key="idem-1",
        contract_id=valid_contract(),
        purpose="ENTRY",
        side=OrderSide.BUY,
        requested_quantity=2,
        reference_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
    )
    attempt = ExecutionAttempt(
        attempt_id="attempt-1",
        intent_id=intent.intent_id,
        requested_quantity=2,
        status=ExecutionAttemptStatus.PREPARED,
    )
    fill = Fill(
        fill_id="fill-1",
        intent_id=intent.intent_id,
        contract_id=intent.contract_id,
        quantity=1,
        price=Decimal("100.05"),
        fees=Decimal("0.5"),
        filled_at=datetime(2026, 9, 24, 10, 1, tzinfo=IST),
    )
    reservation = RiskReservation(
        reservation_id="reservation-1",
        intent_id=intent.intent_id,
        owner="risk-authority",
        amount=Decimal("10"),
        status=RiskReservationStatus.RESERVED,
    )
    assert intent.requested_quantity == 2
    assert attempt.attempt_id != intent.intent_id
    assert fill.quantity == 1
    assert reservation.status is RiskReservationStatus.RESERVED
    with pytest.raises(FrozenInstanceError):
        intent.requested_quantity = 3  # type: ignore[misc]


def test_broker_and_readiness_types_preserve_unknown_states():
    capabilities = BrokerCapabilities(frozenset({"native_stop", "order_lookup", "fills"}))
    assert "fills" in capabilities
    assert isinstance(AmbiguousOutcome(reason="timeout"), AmbiguousOutcome)
    assert isinstance(NotSent(reason="validation"), NotSent)
    assert Readiness(ReadinessStatus.DEGRADED_NO_NEW_ENTRIES, ("broker_unknown",)).can_open_new_entries is False
    assert BrokerOrderSnapshot(
        broker_order_id="broker-1",
        intent_id="intent-1",
        status="UNKNOWN",
        filled_quantity=0,
        requested_quantity=1,
    ).status == "UNKNOWN"


def test_ledger_event_requires_positive_aggregate_sequence_and_is_immutable():
    event = LedgerEvent(
        event_id="event-1",
        aggregate_id="intent-1",
        aggregate_sequence=1,
        event_type="OrderIntentRecorded",
        schema_version=1,
        occurred_at=datetime(2026, 9, 24, 10, 0, tzinfo=IST),
        received_at=datetime(2026, 9, 24, 10, 0, 1, tzinfo=IST),
        correlation_id="corr-1",
        causation_id=None,
        payload={"intent_id": "intent-1"},
        checksum="abc",
    )
    assert event.aggregate_sequence == 1
    with pytest.raises(FrozenInstanceError):
        event.aggregate_sequence = 2  # type: ignore[misc]
    with pytest.raises(ValueError):
        LedgerEvent(
            event_id="event-2",
            aggregate_id="intent-1",
            aggregate_sequence=0,
            event_type="OrderIntentRecorded",
            schema_version=1,
            occurred_at=datetime.now(IST),
            received_at=datetime.now(IST),
            correlation_id="corr-1",
            causation_id=None,
            payload={},
            checksum="abc",
        )
