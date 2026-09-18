from decimal import Decimal

import pytest

from quant.execution.execution_state_machine import ExecutionStateMachine, ExecutionStatus
from quant.contracts.execution_vocabulary import EconomicOperationId


def test_execution_state_machine_accepts_approved_lifecycle():
    machine = ExecutionStateMachine(EconomicOperationId("entry-1"))

    machine.submit()
    machine.partial_fill()
    machine.fill()

    assert machine.status is ExecutionStatus.FILLED


def test_unknown_execution_requires_reconciliation_before_recovery():
    machine = ExecutionStateMachine(EconomicOperationId("close-1"))

    machine.submit()
    machine.unknown()
    machine.reconciliation_required()
    machine.reconciled()

    assert machine.status is ExecutionStatus.RECONCILED


def test_partial_execution_can_enter_reconciliation_required():
    machine = ExecutionStateMachine(EconomicOperationId("entry-partial"))

    machine.submit()
    machine.partial_fill()
    machine.reconciliation_required()

    assert machine.status is ExecutionStatus.RECONCILIATION_REQUIRED


def test_invalid_transition_does_not_silently_change_state():
    machine = ExecutionStateMachine(EconomicOperationId("entry-2"))

    with pytest.raises(ValueError):
        machine.fill()

    assert machine.status is ExecutionStatus.INTENT_CREATED
