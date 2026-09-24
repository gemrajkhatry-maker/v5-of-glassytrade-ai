"""Startup recovery orchestration; runtime readiness remains gated by later waves."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.adapters.persistence.sqlite.projections import SqliteProjector
from glassytrade.application.oms.reconciliation_service import (
    ReconciliationCase,
    ReconciliationReport,
    ReconciliationRequest,
    ReconciliationService,
)
from glassytrade.application.oms.risk_rebuilder import RiskRebuilder
from glassytrade.domain.execution.types import RiskState


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    session_key: str
    account_id: str


@dataclass(frozen=True, slots=True)
class AccountProjection:
    account_id: str
    positions: tuple[Mapping[str, Any], ...]
    realized_pnl: Decimal
    last_sequence: int


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    journal_verified: bool
    rebuilt_sequence: int
    account: AccountProjection
    risk: RiskState
    unresolved_cases: tuple[ReconciliationCase, ...]
    broker_snapshot_available: bool
    recovery_complete: bool
    runtime_ready: bool


class RecoveryService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        broker: Any | None = None,
        journal: SqliteExecutionJournal | None = None,
    ) -> None:
        self.connection = connection
        self.broker = broker
        self.journal = journal or SqliteExecutionJournal(connection)
        self.projector = SqliteProjector(connection)
        self.risk_rebuilder = RiskRebuilder(connection)
        self.reconciliation = ReconciliationService()

    def _broker_snapshot(self) -> tuple[bool, tuple[Mapping[str, Any], ...]]:
        if self.broker is None:
            return False, ()
        try:
            positions = self.broker.list_positions()
            self.broker.list_orders()
            self.broker.list_fills()
        except Exception:
            return False, ()
        normalized = []
        for position in positions:
            if isinstance(position, Mapping):
                normalized.append(dict(position))
            else:
                normalized.append(
                    {
                        "contract_id": getattr(position, "contract_id", ""),
                        "signed_quantity": getattr(position, "signed_quantity", 0),
                        "side": getattr(position, "side", ""),
                        "average_entry": str(getattr(position, "average_entry", "0")),
                        "state": str(getattr(position, "state", "")),
                    }
                )
        return True, tuple(normalized)

    def recover(self, request: RecoveryRequest) -> RecoveryReport:
        self.journal.verify()
        self.projector.rebuild()
        sequence_row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM execution_events"
        ).fetchone()
        rebuilt_sequence = int(sequence_row[0] or 0)
        risk = self.risk_rebuilder.rebuild(request.account_id)
        positions = tuple(
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM positions ORDER BY contract_id"
            )
        )
        account = AccountProjection(
            account_id=request.account_id,
            positions=positions,
            realized_pnl=risk.realized_pnl,
            last_sequence=rebuilt_sequence,
        )
        broker_available, broker_positions = self._broker_snapshot()
        reconciliation: ReconciliationReport = self.reconciliation.compare(
            ReconciliationRequest(
                ledger_events=self.journal.replay(),
                oms_positions=positions,
                broker_positions=broker_positions,
                broker_available=broker_available,
            )
        )
        recovery_complete = (
            reconciliation.accepting_orders and broker_available
        )
        return RecoveryReport(
            journal_verified=True,
            rebuilt_sequence=rebuilt_sequence,
            account=account,
            risk=risk,
            unresolved_cases=reconciliation.cases,
            broker_snapshot_available=broker_available,
            recovery_complete=recovery_complete,
            runtime_ready=False,
        )
