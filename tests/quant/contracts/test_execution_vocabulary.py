from decimal import Decimal

import pytest

from quant.contracts.execution_vocabulary import (
    ContractRef,
    EconomicOperationId,
    ExecutionAttempt,
    ExecutionStatus,
    ExposureState,
    Fill,
    OrderIntent,
)


def test_order_intent_keeps_economic_identity_separate_from_transport_attempt():
    contract = ContractRef(symbol="NIFTY", exchange="NSE", instrument_type="OPTION")
    operation = EconomicOperationId("entry-123")
    intent = OrderIntent(operation_id=operation, contract=contract, side="BUY", quantity=Decimal("50"))
    attempt = ExecutionAttempt(intent=intent, attempt_id="transport-1")

    assert intent.operation_id == operation
    assert attempt.intent.operation_id == operation
    assert attempt.attempt_id != intent.operation_id.value


def test_fill_and_exposure_use_decimal_values_and_explicit_statuses():
    fill = Fill(operation_id=EconomicOperationId("close-1"), quantity=Decimal("25"), price=Decimal("101.25"), status=ExecutionStatus.PARTIALLY_FILLED)
    exposure = ExposureState(symbol="NIFTY", quantity=Decimal("25"), average_price=Decimal("100.00"))

    assert fill.quantity == Decimal("25")
    assert fill.status is ExecutionStatus.PARTIALLY_FILLED
    assert exposure.quantity == Decimal("25")


def test_invalid_execution_vocabulary_values_fail_closed():
    with pytest.raises(ValueError):
        OrderIntent(operation_id=EconomicOperationId("x"), contract=ContractRef("NIFTY", "NSE", "OPTION"), side="HOLD", quantity=Decimal("1"))
