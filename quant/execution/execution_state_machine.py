"""Minimal deterministic execution lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass

from quant.contracts.execution_vocabulary import EconomicOperationId, ExecutionStatus


_TRANSITIONS = {
    ExecutionStatus.INTENT_CREATED: {ExecutionStatus.SUBMITTING},
    ExecutionStatus.SUBMITTING: {
        ExecutionStatus.PARTIALLY_FILLED,
        ExecutionStatus.FILLED,
        ExecutionStatus.REJECTED,
        ExecutionStatus.UNKNOWN,
    },
    ExecutionStatus.PARTIALLY_FILLED: {ExecutionStatus.PARTIALLY_FILLED, ExecutionStatus.FILLED},
    ExecutionStatus.UNKNOWN: {ExecutionStatus.RECONCILIATION_REQUIRED},
    ExecutionStatus.RECONCILIATION_REQUIRED: {ExecutionStatus.RECONCILED},
}


@dataclass
class ExecutionStateMachine:
    operation_id: EconomicOperationId
    status: ExecutionStatus = ExecutionStatus.INTENT_CREATED

    def _transition(self, target: ExecutionStatus) -> None:
        if target not in _TRANSITIONS.get(self.status, set()):
            raise ValueError(f"invalid execution transition: {self.status} -> {target}")
        self.status = target

    def submit(self) -> None:
        self._transition(ExecutionStatus.SUBMITTING)

    def partial_fill(self) -> None:
        self._transition(ExecutionStatus.PARTIALLY_FILLED)

    def fill(self) -> None:
        self._transition(ExecutionStatus.FILLED)

    def reject(self) -> None:
        self._transition(ExecutionStatus.REJECTED)

    def unknown(self) -> None:
        self._transition(ExecutionStatus.UNKNOWN)

    def reconciliation_required(self) -> None:
        self._transition(ExecutionStatus.RECONCILIATION_REQUIRED)

    def reconciled(self) -> None:
        self._transition(ExecutionStatus.RECONCILED)
