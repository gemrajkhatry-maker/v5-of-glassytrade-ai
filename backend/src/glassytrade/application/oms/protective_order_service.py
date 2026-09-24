"""Durable preparation and verification of protective stops."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.domain.execution.stop import StopState, transition_stop_state
from glassytrade.domain.execution.types import Fill, ProtectionReceipt, ProtectionStatus
from glassytrade.domain.ledger.events import LedgerEvent


class ProtectiveOrderService:
    def __init__(
        self,
        connection: sqlite3.Connection | None = None,
        *,
        journal: SqliteExecutionJournal | None = None,
        broker: Any | None = None,
    ) -> None:
        self.connection = connection
        self.jroker = broker
        self.journal = journal or (SqliteExecutionJournal(connection) if connection else None)
        self._records: dict[str, ProtectionReceipt] = {}
        self._position_quantities: dict[str, int] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _persist(self, receipt: ProtectionReceipt, event_type: str, payload: dict[str, Any]) -> None:
        if self.connection is None:
            self._records[receipt.position_id] = receipt
            return
        now = self._now().isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "INSERT INTO protection_orders(" 
                "receipt_id, position_id, status, desired_stop, effective_stop, broker_order_id, "
                "protection_quantity, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(receipt_id) DO UPDATE SET status=excluded.status, "
                "effective_stop=excluded.effective_stop, protection_quantity=excluded.protection_quantity, updated_at=excluded.updated_at",
                (
                    receipt.receipt_id,
                    receipt.position_id,
                    receipt.status.value,
                    str(receipt.desired_stop),
                    str(receipt.effective_stop) if receipt.effective_stop is not None else None,
                    receipt.broker_order_id,
                    receipt.protection_quantity,
                    now,
                ),
            )
            if self.journal is not None:
                row = self.connection.execute(
                    "SELECT COALESCE(MAX(aggregate_sequence), 0) FROM execution_events WHERE aggregate_id = ?",
                    (receipt.position_id,),
                ).fetchone()
                event = LedgerEvent(
                    event_id=f"protection:{receipt.receipt_id}",
                    aggregate_id=receipt.position_id,
                    aggregate_sequence=int(row[0] or 0) + 1,
                    event_type=event_type,
                    schema_version=1,
                    occurred_at=self._now(),
                    received_at=self._now(),
                    correlation_id=receipt.receipt_id,
                    causation_id=receipt.receipt_id,
                    payload=payload,
                )
                self.journal.append_in_transaction(event)
                self.journal.before_commit()
            self.connection.execute("COMMIT")
            self._records[receipt.position_id] = receipt
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def _current(self, position_id: str) -> ProtectionReceipt | None:
        return self._records.get(position_id)

    def ensure_for_fill(self, fill: Fill, *, stop_price: Decimal) -> ProtectionReceipt:
        position_id = fill.contract_id.key
        current = self._current(position_id)
        quantity = (current.protection_quantity if current else 0) + fill.quantity
        receipt = ProtectionReceipt(
            receipt_id=f"protection:{position_id}:{quantity}",
            position_id=position_id,
            status=ProtectionStatus.PREPARED,
            desired_stop=Decimal(str(stop_price)),
            effective_stop=None,
            broker_order_id=None,
            protection_quantity=quantity,
        )
        self._persist(
            receipt,
            "ProtectionPrepared",
            {
                "receipt_id": receipt.receipt_id,
                "position_id": position_id,
                "status": receipt.status.value,
                "desired_stop": str(receipt.desired_stop),
                "protection_quantity": quantity,
            },
        )
        return receipt

    def ratchet(self, position_id: str, desired_stop: Decimal, reason: str) -> ProtectionReceipt:
        current = self._current(position_id)
        if current is None:
            raise KeyError(position_id)
        receipt = ProtectionReceipt(
            receipt_id=f"protection:{position_id}:ratchet:{len(self._records) + 1}",
            position_id=position_id,
            status=ProtectionStatus.REPLACING,
            desired_stop=Decimal(str(desired_stop)),
            effective_stop=None,
            broker_order_id=None,
            protection_quantity=current.protection_quantity,
        )
        self._persist(
            receipt,
            "ProtectionReplacing",
            {
                "receipt_id": receipt.receipt_id,
                "position_id": position_id,
                "status": receipt.status.value,
                "desired_stop": str(receipt.desired_stop),
                "reason": reason,
            },
        )
        return receipt

    def retire_for_exit(self, position_id: str, exit_fill: Fill) -> ProtectionReceipt:
        current = self._current(position_id)
        desired = current.desired_stop if current else Decimal("0")
        receipt = ProtectionReceipt(
            receipt_id=f"protection:{position_id}:retired:{exit_fill.fill_id}",
            position_id=position_id,
            status=ProtectionStatus.RETIRED,
            desired_stop=desired,
            effective_stop=None,
            broker_order_id=None,
            protection_quantity=0,
        )
        self._persist(
            receipt,
            "ProtectionRetired",
            {
                "receipt_id": receipt.receipt_id,
                "position_id": position_id,
                "exit_fill_id": exit_fill.fill_id,
                "status": receipt.status.value,
            },
        )
        return receipt

    def activate(
        self,
        receipt_id: str,
        *,
        broker_order_id: str,
        effective_stop: Decimal,
    ) -> ProtectionReceipt:
        receipt = next(
            (item for item in self._records.values() if item.receipt_id == receipt_id),
            None,
        )
        if receipt is None:
            raise KeyError(receipt_id)
        transition_stop_state(StopState(receipt.status.value), StopState.ACTIVATING)
        transition_stop_state(StopState.ACTIVATING, StopState.ACTIVE)
        activated = ProtectionReceipt(
            receipt_id=receipt.receipt_id,
            position_id=receipt.position_id,
            status=ProtectionStatus.ACTIVE,
            desired_stop=receipt.desired_stop,
            effective_stop=Decimal(str(effective_stop)),
            broker_order_id=broker_order_id,
            protection_quantity=receipt.protection_quantity,
        )
        self._persist(
            activated,
            "ProtectionActivated",
            {
                "receipt_id": activated.receipt_id,
                "position_id": activated.position_id,
                "broker_order_id": broker_order_id,
                "effective_stop": str(activated.effective_stop),
            },
        )
        return activated

    def set_position_quantity(self, position_id: str, quantity: int) -> None:
        if quantity < 0:
            raise ValueError("position quantity must be non-negative")
        self._position_quantities[position_id] = quantity

    def verify(self, position_id: str) -> "ProtectionVerification":
        receipt = self._current(position_id)
        position_quantity = self._position_quantities.get(position_id, 0)
        protected = receipt.protection_quantity if receipt and receipt.status is not ProtectionStatus.RETIRED else 0
        if not receipt or protected == 0:
            reason = "protection_missing"
        elif protected != position_quantity:
            reason = "protected_quantity_mismatch"
        elif receipt.status is not ProtectionStatus.ACTIVE:
            reason = "protection_not_broker_confirmed"
        else:
            reason = ""
        return ProtectionVerification(
            position_id=position_id,
            verified=not reason,
            protected_quantity=protected,
            position_quantity=position_quantity,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class ProtectionVerification:
    position_id: str
    verified: bool
    protected_quantity: int
    position_quantity: int
    reason: str
