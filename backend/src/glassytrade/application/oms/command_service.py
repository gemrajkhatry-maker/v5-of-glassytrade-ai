"""Durable OMS command service for the target execution path."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from glassytrade.adapters.persistence.sqlite.journal import SqliteExecutionJournal
from glassytrade.application.commands.evaluate_exit import finalize_exit_intent
from glassytrade.application.commands.submit_entry import finalize_entry_intent
from glassytrade.application.ports.broker import BrokerPlaceRequest
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.oms import (
    IngestResult,
    PreparedOrder,
    ReconciliationRequired,
)
from glassytrade.domain.execution.types import (
    ExecutionAttempt,
    ExecutionAttemptStatus,
    Fill,
    OrderIntent,
    OrderSide,
    OrderStatus,
    RiskReservation,
    RiskReservationStatus,
    RiskState,
)
from glassytrade.domain.ledger.events import LedgerEvent
from glassytrade.domain.risk.reservation import EntryRiskRequest, RiskPolicy, reserve_entry
from glassytrade.domain.strategy.intent import EntryIntent, ExitIntent


class IdempotencyConflict(RuntimeError):
    """Raised when one idempotency key is reused for different content."""


class OmsCommandService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        journal: SqliteExecutionJournal | None = None,
        max_reserved_risk: Decimal = Decimal("1000000000"),
    ) -> None:
        self.connection = connection
        self.journal = journal or SqliteExecutionJournal(connection)
        self.max_reserved_risk = Decimal(str(max_reserved_risk))
        self._attempts: dict[str, ExecutionAttempt] = {}
        self._intents: dict[str, OrderIntent] = {}
        self._reservations: dict[str, RiskReservation] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def _request_hash(cls, intent: OrderIntent) -> str:
        payload = {
            "intent_id": intent.intent_id,
            "contract_id": intent.contract_id.key,
            "purpose": intent.purpose,
            "side": intent.side,
            "quantity": intent.requested_quantity,
            "reference_price": str(intent.reference_price),
            "stop_price": str(intent.stop_price),
            "target_price": str(intent.target_price),
        }
        return hashlib.sha256(cls._json(payload).encode("utf-8")).hexdigest()

    def _next_sequence(self, aggregate_id: str) -> int:
        row = self.connection.execute(
            "SELECT MAX(aggregate_sequence) FROM execution_events WHERE aggregate_id = ?",
            (aggregate_id,),
        ).fetchone()
        return int(row[0] or 0) + 1

    def _event(
        self,
        *,
        event_id: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        causation_id: str | None = None,
    ) -> LedgerEvent:
        now = self._now()
        return LedgerEvent(
            event_id=event_id,
            aggregate_id=aggregate_id,
            aggregate_sequence=self._next_sequence(aggregate_id),
            event_type=event_type,
            schema_version=1,
            occurred_at=now,
            received_at=now,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload,
        )

    def _risk_state(self) -> RiskState:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM risk_reservations WHERE status != ?",
            (RiskReservationStatus.RELEASED.value,),
        ).fetchone()
        return RiskState("oms", reserved_risk=Decimal(str(row[0])))

    def _persist_prepared(
        self,
        intent: OrderIntent,
        reservation: RiskReservation,
        attempt: ExecutionAttempt,
    ) -> None:
        request_hash = self._request_hash(intent)
        self.connection.execute(
            "INSERT INTO order_intents(" 
            "intent_id, idempotency_key, contract_id, purpose, side, requested_quantity, "
            "request_hash, reference_price, stop_price, target_price, status, created_sequence, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                intent.intent_id,
                intent.idempotency_key,
                intent.contract_id.key,
                intent.purpose,
                intent.side,
                intent.requested_quantity,
                request_hash,
                str(intent.reference_price) if intent.reference_price is not None else None,
                str(intent.stop_price) if intent.stop_price is not None else None,
                str(intent.target_price) if intent.target_price is not None else None,
                OrderStatus.RESERVED.value,
                0,
                self._now().isoformat(),
            ),
        )
        self.connection.execute(
            "INSERT INTO order_attempts(" 
            "attempt_id, intent_id, status, broker_order_id, correlation_id, requested_quantity, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                attempt.attempt_id,
                attempt.intent_id,
                attempt.status.value,
                attempt.broker_order_id,
                attempt.correlation_id,
                attempt.requested_quantity,
                self._now().isoformat(),
            ),
        )
        self.connection.execute(
            "INSERT INTO risk_reservations(" 
            "reservation_id, intent_id, owner, amount, released_amount, status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                reservation.reservation_id,
                reservation.intent_id,
                reservation.owner,
                str(reservation.amount),
                str(reservation.released_amount),
                reservation.status.value,
                self._now().isoformat(),
            ),
        )
        self.journal.append_in_transaction(
            self._event(
                event_id=f"intent-recorded:{intent.intent_id}",
                aggregate_id=intent.intent_id,
                event_type="OrderIntentRecorded",
                payload={
                    "intent_id": intent.intent_id,
                    "idempotency_key": intent.idempotency_key,
                    "contract_id": intent.contract_id.key,
                    "side": intent.side,
                    "purpose": intent.purpose,
                    "requested_quantity": intent.requested_quantity,
                    "request_hash": request_hash,
                },
                correlation_id=intent.idempotency_key,
            )
        )
        self.journal.append_in_transaction(
            self._event(
                event_id=f"attempt-prepared:{attempt.attempt_id}",
                aggregate_id=attempt.attempt_id,
                event_type="ExecutionAttemptPrepared",
                payload={
                    "attempt_id": attempt.attempt_id,
                    "intent_id": attempt.intent_id,
                    "status": attempt.status.value,
                    "requested_quantity": attempt.requested_quantity,
                    "correlation_id": attempt.correlation_id,
                },
                correlation_id=attempt.correlation_id,
                causation_id=f"intent-recorded:{intent.intent_id}",
            )
        )
        self.journal.append_in_transaction(
            self._event(
                event_id=f"reservation-recorded:{reservation.reservation_id}",
                aggregate_id=reservation.reservation_id,
                event_type="RiskReservationRecorded",
                payload={
                    "reservation_id": reservation.reservation_id,
                    "intent_id": reservation.intent_id,
                    "owner": reservation.owner,
                    "amount": str(reservation.amount),
                    "status": reservation.status.value,
                },
                correlation_id=intent.idempotency_key,
                causation_id=f"intent-recorded:{intent.intent_id}",
            )
        )
        self.connection.execute(
            "UPDATE order_intents SET created_sequence = ? WHERE intent_id = ?",
            (self._next_sequence(intent.intent_id) - 1, intent.intent_id),
        )

    def _load_prepared(self, intent_id: str) -> PreparedOrder:
        row = self.connection.execute(
            "SELECT * FROM order_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise KeyError(intent_id)
        intent = OrderIntent(
            intent_id=row["intent_id"],
            idempotency_key=row["idempotency_key"],
            contract_id=self._contract_from_key(row["contract_id"]),
            purpose=row["purpose"],
            side=row["side"],
            requested_quantity=int(row["requested_quantity"]),
            reference_price=Decimal(row["reference_price"]) if row["reference_price"] else None,
            stop_price=Decimal(row["stop_price"]) if row["stop_price"] else None,
            target_price=Decimal(row["target_price"]) if row["target_price"] else None,
        )
        attempt_row = self.connection.execute(
            "SELECT * FROM order_attempts WHERE intent_id = ? ORDER BY created_at LIMIT 1",
            (intent_id,),
        ).fetchone()
        reservation_row = self.connection.execute(
            "SELECT * FROM risk_reservations WHERE intent_id = ? LIMIT 1", (intent_id,)
        ).fetchone()
        attempt = ExecutionAttempt(
            attempt_id=attempt_row["attempt_id"],
            intent_id=intent_id,
            requested_quantity=int(attempt_row["requested_quantity"]),
            status=ExecutionAttemptStatus(attempt_row["status"]),
            broker_order_id=attempt_row["broker_order_id"],
            correlation_id=attempt_row["correlation_id"],
        )
        reservation = RiskReservation(
            reservation_id=reservation_row["reservation_id"],
            intent_id=intent_id,
            owner=reservation_row["owner"],
            amount=Decimal(reservation_row["amount"]),
            status=RiskReservationStatus(reservation_row["status"]),
            released_amount=Decimal(reservation_row["released_amount"]),
        )
        return PreparedOrder(intent, attempt, reservation)

    @staticmethod
    def _contract_from_key(value: str) -> ContractId:
        parts = value.split("|")
        if len(parts) != 7:
            raise ValueError(f"invalid persisted contract identity: {value}")
        return ContractId(*parts[:4], parts[4] or None, parts[5], parts[6])

    def _prepare(self, intent: OrderIntent) -> PreparedOrder:
        existing = self.connection.execute(
            "SELECT intent_id, request_hash FROM order_intents WHERE idempotency_key = ?",
            (intent.idempotency_key,),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != self._request_hash(intent):
                raise IdempotencyConflict(intent.idempotency_key)
            return self._load_prepared(existing["intent_id"])

        state = self._risk_state()
        entry_request = EntryRiskRequest(
            intent_id=intent.intent_id,
            owner="risk-authority",
            risk_amount=(
                abs(intent.reference_price - intent.stop_price) * intent.requested_quantity
                if intent.reference_price is not None and intent.stop_price is not None
                else Decimal("1")
            ),
        )
        decision = reserve_entry(
            state,
            entry_request,
            RiskPolicy(max_reserved_risk=self.max_reserved_risk),
        )
        if not decision.accepted or decision.reservation is None:
            raise ValueError(decision.reason or "risk reservation rejected")
        attempt = ExecutionAttempt(
            attempt_id=f"attempt:{intent.intent_id}",
            intent_id=intent.intent_id,
            requested_quantity=intent.requested_quantity,
            status=ExecutionAttemptStatus.PREPARED,
            correlation_id=intent.idempotency_key,
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._persist_prepared(intent, decision.reservation, attempt)
            self.journal.before_commit()
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return PreparedOrder(intent, attempt, decision.reservation)

    def prepare_entry(self, intent: EntryIntent) -> PreparedOrder:
        return self._prepare(
            finalize_entry_intent(intent, executable_quantity=intent.desired_quantity)
        )

    def prepare_exit(self, intent: ExitIntent) -> PreparedOrder:
        return self._prepare(finalize_exit_intent(intent))

    def _attempt(self, attempt_id: str) -> ExecutionAttempt:
        row = self.connection.execute(
            "SELECT * FROM order_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return ExecutionAttempt(
            attempt_id=row["attempt_id"],
            intent_id=row["intent_id"],
            requested_quantity=int(row["requested_quantity"]),
            status=ExecutionAttemptStatus(row["status"]),
            broker_order_id=row["broker_order_id"],
            correlation_id=row["correlation_id"],
        )

    def claim_dispatch(self, attempt_id: str) -> BrokerPlaceRequest:
        attempt = self._attempt(attempt_id)
        if attempt.status is ExecutionAttemptStatus.UNKNOWN:
            raise ReconciliationRequired(attempt_id)
        if attempt.status is not ExecutionAttemptStatus.PREPARED:
            raise ReconciliationRequired(f"attempt is not dispatchable: {attempt.status.value}")
        intent = self._load_prepared(attempt.intent_id).intent
        request = BrokerPlaceRequest(
            attempt_id=attempt.attempt_id,
            contract_id=intent.contract_id,
            side=OrderSide(intent.side),
            quantity=intent.requested_quantity,
            correlation_id=attempt.correlation_id,
            reference_price=intent.reference_price,
            stop_price=intent.stop_price,
            target_price=intent.target_price,
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE order_attempts SET status = ? WHERE attempt_id = ?",
                (ExecutionAttemptStatus.DISPATCHING.value, attempt_id),
            )
            self.journal.append_in_transaction(
                self._event(
                    event_id=f"attempt-dispatching:{attempt_id}",
                    aggregate_id=attempt_id,
                    event_type="ExecutionAttemptDispatching",
                    payload={"attempt_id": attempt_id, "intent_id": attempt.intent_id},
                    correlation_id=attempt.correlation_id,
                )
            )
            self.journal.before_commit()
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return request

    def mark_attempt_unknown(self, attempt_id: str) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE order_attempts SET status = ? WHERE attempt_id = ?",
                (ExecutionAttemptStatus.UNKNOWN.value, attempt_id),
            )
            self.journal.append_in_transaction(
                self._event(
                    event_id=f"attempt-unknown:{attempt_id}",
                    aggregate_id=attempt_id,
                    event_type="ExecutionAttemptUnknown",
                    payload={"attempt_id": attempt_id},
                    correlation_id=attempt_id,
                )
            )
            self.journal.before_commit()
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def ingest_receipt(self, receipt: Fill) -> IngestResult:
        receipt_id = f"fill:{receipt.fill_id}"
        existing = self.connection.execute(
            "SELECT event_id FROM broker_receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if existing is not None:
            return IngestResult(False, receipt_id, existing["event_id"])
        payload = {
            "fill_id": receipt.fill_id,
            "intent_id": receipt.intent_id,
            "contract_id": receipt.contract_id.key,
            "quantity": receipt.quantity,
            "price": str(receipt.price),
            "fees": str(receipt.fees),
            "filled_at": receipt.filled_at.isoformat(),
        }
        now = self._now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "INSERT INTO broker_receipts(receipt_id, event_id, payload_json, received_at) VALUES (?, ?, ?, ?)",
                (receipt_id, f"broker-receipt:{receipt.fill_id}", self._json(payload), now.isoformat()),
            )
            broker_event = self._event(
                event_id=f"broker-receipt:{receipt.fill_id}",
                aggregate_id=receipt.intent_id,
                event_type="BrokerReceiptRecorded",
                payload=payload,
                correlation_id=receipt.fill_id,
            )
            self.journal.append_in_transaction(broker_event)
            fill_event = self._event(
                event_id=f"fill-recorded:{receipt.fill_id}",
                aggregate_id=receipt.intent_id,
                event_type="FillRecorded",
                payload=payload,
                correlation_id=receipt.fill_id,
                causation_id=broker_event.event_id,
            )
            self.journal.append_in_transaction(fill_event)
            self.journal.before_commit()
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return IngestResult(True, receipt_id, fill_event.event_id, receipt)

    def create_zero_fill_fallback(self, intent_id: str, receipt_id: str) -> ExecutionAttempt:
        prepared = self._load_prepared(intent_id)
        if prepared.attempt.status not in {
            ExecutionAttemptStatus.REJECTED,
            ExecutionAttemptStatus.EXPIRED,
        }:
            raise ReconciliationRequired("zero-fill fallback requires a terminal no-fill attempt")
        attempt = ExecutionAttempt(
            attempt_id=f"attempt:{intent_id}:fallback:{receipt_id}",
            intent_id=intent_id,
            requested_quantity=prepared.intent.requested_quantity,
            status=ExecutionAttemptStatus.PREPARED,
            correlation_id=prepared.attempt.correlation_id,
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "INSERT INTO order_attempts(attempt_id, intent_id, status, broker_order_id, correlation_id, requested_quantity, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    intent_id,
                    attempt.status.value,
                    None,
                    attempt.correlation_id,
                    attempt.requested_quantity,
                    self._now().isoformat(),
                ),
            )
            self.journal.append_in_transaction(
                self._event(
                    event_id=f"attempt-prepared:{attempt.attempt_id}",
                    aggregate_id=attempt.attempt_id,
                    event_type="ExecutionAttemptPrepared",
                    payload={"attempt_id": attempt.attempt_id, "intent_id": intent_id},
                    correlation_id=attempt.correlation_id,
                    causation_id=receipt_id,
                )
            )
            self.journal.before_commit()
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return attempt

    def attempt_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM order_attempts").fetchone()[0])

    def intent_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0])
