"""Single writer for execution commands and account projection."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, TypeAlias

from glassytrade.application.oms.command_service import OmsCommandService
from glassytrade.application.oms.recovery_service import AccountProjection
from glassytrade.domain.execution.types import Fill
from glassytrade.domain.strategy.intent import EntryIntent, ExitIntent


@dataclass(frozen=True)
class SubmitEntryCommand:
    intent: EntryIntent


@dataclass(frozen=True)
class SubmitExitCommand:
    intent: ExitIntent


@dataclass(frozen=True)
class IngestBrokerReceiptCommand:
    receipt: Fill


@dataclass(frozen=True)
class EmergencyHaltCommand:
    reason: str


ExecutionCommand: TypeAlias = (
    SubmitEntryCommand
    | SubmitExitCommand
    | IngestBrokerReceiptCommand
    | EmergencyHaltCommand
)


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    result: Any | None = None
    reason: str | None = None


class ExecutionCoordinator:
    def __init__(
        self,
        oms_service: OmsCommandService,
        *,
        account_id: str,
        max_pending: int = 1000,
    ) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self.oms_service = oms_service
        self.account_id = account_id
        self.max_pending = max_pending
        self.pending: deque[ExecutionCommand] = deque()
        self.mutation_count = 0
        self._mutated_keys: set[str] = set()
        self.halted = False

    def execute(self, command: ExecutionCommand) -> ExecutionOutcome:
        if isinstance(command, EmergencyHaltCommand):
            self.halted = True
            return ExecutionOutcome("halted", reason=command.reason)
        if self.halted:
            return ExecutionOutcome("reconciliation_required", reason="coordinator halted")
        if len(self.pending) >= self.max_pending:
            return ExecutionOutcome("deferred", reason="coordinator queue is full")
        self.pending.append(command)
        try:
            if isinstance(command, SubmitEntryCommand):
                result = self.oms_service.prepare_entry(command.intent)
            elif isinstance(command, SubmitExitCommand):
                result = self.oms_service.prepare_exit(command.intent)
            elif isinstance(command, IngestBrokerReceiptCommand):
                result = self.oms_service.ingest_receipt(command.receipt)
            else:
                return ExecutionOutcome("rejected", reason="unsupported command")
            mutation_key = self._mutation_key(command, result)
            if mutation_key not in self._mutated_keys:
                self._mutated_keys.add(mutation_key)
                self.mutation_count += 1
            return ExecutionOutcome("accepted", result)
        except Exception as exc:
            return ExecutionOutcome("rejected", reason=str(exc))
        finally:
            self.pending.pop()

    @staticmethod
    def _mutation_key(command: ExecutionCommand, result: Any) -> str:
        if isinstance(command, (SubmitEntryCommand, SubmitExitCommand)):
            return f"intent:{command.intent.intent_id}"
        if isinstance(command, IngestBrokerReceiptCommand):
            return f"receipt:{command.receipt.fill_id}"
        return f"result:{id(result)}"

    def project_account(self, account_id: str, *, after_sequence: int = 0) -> AccountProjection:
        if account_id != self.account_id:
            raise ValueError("unknown account")
        rows = self.oms_service.connection.execute(
            "SELECT * FROM positions ORDER BY contract_id"
        ).fetchall()
        sequence = self.oms_service.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM execution_events"
        ).fetchone()[0]
        if int(sequence) < after_sequence:
            raise ValueError("projection sequence is ahead of the account")
        risk = self.oms_service._risk_state()
        return AccountProjection(
            account_id=account_id,
            positions=tuple(dict(row) for row in rows),
            realized_pnl=risk.realized_pnl,
            last_sequence=int(sequence),
        )

    def drain(self) -> None:
        self.pending.clear()

    def readiness(self):
        if self.halted:
            from glassytrade.domain.execution.types import Readiness, ReadinessStatus

            return Readiness(ReadinessStatus.NOT_READY, ("coordinator_halted",))
        return None
