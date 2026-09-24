"""Deterministic projection rebuild from the execution journal."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

_PROJECTION_TABLES = (
    "order_attempts",
    "fills",
    "positions",
    "risk_reservations",
    "protection_orders",
    "order_intents",
    "reconciliation_cases",
)


class SqliteProjector:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        failure_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.connection = connection
        self.failure_hook = failure_hook

    def _hook(self, stage: str) -> None:
        if self.failure_hook is not None:
            self.failure_hook(stage)

    @staticmethod
    def _text(payload: Mapping[str, Any], key: str, default: str = "") -> str:
        value = payload.get(key, default)
        return str(value)

    def _event_sequence(self, event_id: str) -> int:
        row = self.connection.execute(
            "SELECT sequence FROM execution_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"event not found: {event_id}")
        return int(row[0])

    def _project_event(self, event) -> None:
        payload = dict(event.payload)
        sequence = self._event_sequence(event.event_id)
        if event.event_type in {"IntentCreated", "OrderIntentRecorded"}:
            self.connection.execute(
                "INSERT INTO order_intents(" 
                "intent_id, idempotency_key, contract_id, purpose, side, requested_quantity, "
                "request_hash, reference_price, stop_price, target_price, status, created_sequence, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(intent_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
                (
                    self._text(payload, "intent_id", event.aggregate_id),
                    self._text(payload, "idempotency_key", event.aggregate_id),
                    self._text(payload, "contract_id"),
                    self._text(payload, "purpose", "ENTRY"),
                    self._text(payload, "side", "BUY"),
                    int(payload.get("requested_quantity", 1)),
                    self._text(payload, "request_hash"),
                    self._text(payload, "reference_price") or None,
                    self._text(payload, "stop_price") or None,
                    self._text(payload, "target_price") or None,
                    self._text(payload, "status", "READY"),
                    event.aggregate_sequence,
                    event.occurred_at.isoformat(),
                ),
            )
        elif event.event_type in {"OrderAttemptPrepared", "ExecutionAttemptPrepared"}:
            self.connection.execute(
                "INSERT INTO order_attempts(" 
                "attempt_id, intent_id, status, broker_order_id, correlation_id, requested_quantity, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(attempt_id) DO UPDATE SET status=excluded.status",
                (
                    self._text(payload, "attempt_id"),
                    self._text(payload, "intent_id", event.aggregate_id),
                    self._text(payload, "status", "PREPARED"),
                    self._text(payload, "broker_order_id") or None,
                    self._text(payload, "correlation_id", event.correlation_id),
                    int(payload.get("requested_quantity", 1)),
                    event.occurred_at.isoformat(),
                ),
            )
        elif event.event_type == "FillRecorded":
            quantity = int(payload.get("quantity", 0))
            if quantity <= 0:
                raise ValueError("fill quantity must be positive")
            fill_id = self._text(payload, "fill_id", event.event_id)
            contract_id = self._text(payload, "contract_id")
            price = self._text(payload, "price", "0")
            self.connection.execute(
                "INSERT INTO fills(" 
                "fill_id, intent_id, contract_id, quantity, price, fees, filled_at, event_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fill_id,
                    self._text(payload, "intent_id", event.aggregate_id),
                    contract_id,
                    quantity,
                    price,
                    self._text(payload, "fees", "0"),
                    event.occurred_at.isoformat(),
                    sequence,
                ),
            )
            side = self._text(payload, "side", "BUY").upper()
            signed = quantity if side == "BUY" else -quantity
            existing = self.connection.execute(
                "SELECT signed_quantity, average_entry FROM positions WHERE contract_id = ?",
                (contract_id,),
            ).fetchone()
            if existing is None:
                self.connection.execute(
                    "INSERT INTO positions(" 
                    "contract_id, position_id, signed_quantity, average_entry, current_stop, state, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        contract_id,
                        self._text(payload, "position_id", contract_id),
                        signed,
                        price,
                        None,
                        "OPEN" if signed else "FLAT",
                        event.occurred_at.isoformat(),
                    ),
                )
            else:
                old_quantity = int(existing["signed_quantity"])
                new_quantity = old_quantity + signed
                total = abs(old_quantity) + abs(signed)
                average = (
                    (Decimal(str(existing["average_entry"])) * abs(old_quantity)
                    + Decimal(price) * abs(signed))
                    / Decimal(total)
                    if total
                    else Decimal(price)
                )
                self.connection.execute(
                    "UPDATE positions SET signed_quantity = ?, average_entry = ?, state = ?, updated_at = ? "
                    "WHERE contract_id = ?",
                    (
                        new_quantity,
                        str(average),
                        "OPEN" if new_quantity else "FLAT",
                        event.occurred_at.isoformat(),
                        contract_id,
                    ),
                )
        elif event.event_type == "RiskReservationRecorded":
            self.connection.execute(
                "INSERT INTO risk_reservations(" 
                "reservation_id, intent_id, owner, amount, released_amount, status, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(reservation_id) DO UPDATE SET status=excluded.status",
                (
                    self._text(payload, "reservation_id"),
                    self._text(payload, "intent_id", event.aggregate_id),
                    self._text(payload, "owner", "risk-authority"),
                    self._text(payload, "amount", "0"),
                    self._text(payload, "released_amount", "0"),
                    self._text(payload, "status", "RESERVED"),
                    event.occurred_at.isoformat(),
                ),
            )
        elif event.event_type in {"ProtectionPrepared", "ProtectionActivated"}:
            self.connection.execute(
                "INSERT INTO protection_orders(" 
                "receipt_id, position_id, status, desired_stop, effective_stop, broker_order_id, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(receipt_id) DO UPDATE SET status=excluded.status",
                (
                    self._text(payload, "receipt_id", event.event_id),
                    self._text(payload, "position_id"),
                    self._text(payload, "status", "PREPARED"),
                    self._text(payload, "desired_stop", "0"),
                    self._text(payload, "effective_stop") or None,
                    self._text(payload, "broker_order_id") or None,
                    event.occurred_at.isoformat(),
                ),
            )
        elif event.event_type == "ReconciliationCompleted":
            self.connection.execute(
                "INSERT INTO reconciliation_cases(" 
                "case_id, contract_id, discrepancy, expected_state, observed_state, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._text(payload, "case_id", event.event_id),
                    self._text(payload, "contract_id") or None,
                    self._text(payload, "discrepancy", "none"),
                    json.dumps(payload.get("expected_state", {}), sort_keys=True),
                    json.dumps(payload.get("observed_state", {}), sort_keys=True),
                    self._text(payload, "status", "OPEN"),
                    event.occurred_at.isoformat(),
                ),
            )

    def rebuild(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for table in _PROJECTION_TABLES:
                self.connection.execute(f"DELETE FROM {table}")
            rows = self.connection.execute(
                "SELECT event_id FROM execution_events ORDER BY sequence"
            ).fetchall()
            for row in rows:
                event_row = self.connection.execute(
                    "SELECT * FROM execution_events WHERE event_id = ?", (row["event_id"],)
                ).fetchone()
                self._project_event(self._event_from_row(event_row))
                self._hook("after_projection")
            self._hook("before_projection_commit")
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _event_from_row(row: sqlite3.Row):
        from glassytrade.domain.ledger.events import LedgerEvent

        return LedgerEvent(
            event_id=row["event_id"],
            aggregate_id=row["aggregate_id"],
            aggregate_sequence=int(row["aggregate_sequence"]),
            event_type=row["event_type"],
            schema_version=int(row["schema_version"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            received_at=datetime.fromisoformat(row["received_at"]),
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            payload=json.loads(row["payload_json"]),
            checksum=row["checksum"],
        )

    def order_intent(self, intent_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM order_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        return dict(row) if row else None

    def position_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM positions ORDER BY contract_id")]
