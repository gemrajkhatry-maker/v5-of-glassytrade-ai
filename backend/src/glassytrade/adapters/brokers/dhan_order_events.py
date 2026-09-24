"""Receipt-first normalization for Dhan order events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

from glassytrade.domain.execution.types import BrokerFill, BrokerOrderSnapshot
from glassytrade.domain.ledger.events import LedgerEvent


@dataclass(frozen=True)
class DhanReceipt:
    event_id: str
    kind: str
    broker_order_id: str
    intent_id: str
    occurred_at: datetime
    payload: Mapping[str, Any]
    quantity: int = 0
    price: str | Decimal = "0"
    cumulative_filled_quantity: int = 0

    def __post_init__(self) -> None:
        for name in ("event_id", "kind", "broker_order_id", "intent_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.quantity < 0 or self.cumulative_filled_quantity < 0:
            raise ValueError("receipt quantities must be non-negative")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class BrokerEventIngestor:
    def __init__(self, *, journal: Any | None = None) -> None:
        self._journal = journal
        self._journal_sequences: dict[str, int] = {}
        self._seen: dict[str, BrokerFill | BrokerOrderSnapshot] = {}
        self._semantic_seen: set[tuple[object, ...]] = set()
        self._cumulative: dict[str, int] = {}
        self._fills: dict[str, list[BrokerFill]] = {}
        self.raw_receipts: list[DhanReceipt] = []

    def _persist_raw_receipt(self, receipt: DhanReceipt) -> None:
        if self._journal is None:
            return
        sequence = self._journal_sequences.get(receipt.broker_order_id, 0) + 1
        self._journal_sequences[receipt.broker_order_id] = sequence
        self._journal.append(
            LedgerEvent(
                event_id=f"broker-receipt:{receipt.event_id}",
                aggregate_id=receipt.broker_order_id,
                aggregate_sequence=sequence,
                event_type=f"Broker{receipt.kind.title()}Receipt",
                schema_version=1,
                occurred_at=receipt.occurred_at,
                received_at=datetime.now(UTC),
                correlation_id=receipt.event_id,
                causation_id=None,
                payload={
                    "broker_event_id": receipt.event_id,
                    "broker_order_id": receipt.broker_order_id,
                    "intent_id": receipt.intent_id,
                    "kind": receipt.kind,
                    "quantity": receipt.quantity,
                    "price": str(receipt.price),
                    "cumulative_filled_quantity": receipt.cumulative_filled_quantity,
                    "raw": dict(receipt.payload),
                },
            )
        )

    def ingest(self, receipt: DhanReceipt) -> tuple[BrokerFill | BrokerOrderSnapshot, ...]:
        if receipt.event_id in self._seen:
            return ()
        self.raw_receipts.append(receipt)
        self._persist_raw_receipt(receipt)
        semantic_key = (
            receipt.kind,
            receipt.broker_order_id,
            receipt.quantity,
            str(receipt.price),
            receipt.cumulative_filled_quantity,
        )
        if semantic_key in self._semantic_seen:
            return ()
        self._semantic_seen.add(semantic_key)
        if receipt.kind == "fill":
            previous = self._cumulative.get(receipt.broker_order_id, 0)
            if receipt.cumulative_filled_quantity < previous:
                self._seen[receipt.event_id] = previous
                return ()
            normalized = BrokerFill(
                broker_fill_id=receipt.event_id,
                broker_order_id=receipt.broker_order_id,
                intent_id=receipt.intent_id,
                quantity=receipt.quantity,
                price=Decimal(str(receipt.price)),
                fees=Decimal(str(receipt.payload.get("fees", "0"))),
                filled_at=receipt.occurred_at,
                cumulative_filled_quantity=receipt.cumulative_filled_quantity,
            )
            self._cumulative[receipt.broker_order_id] = receipt.cumulative_filled_quantity
            self._fills.setdefault(receipt.broker_order_id, []).append(normalized)
            self._seen[receipt.event_id] = normalized
            return (normalized,)
        if receipt.kind == "order":
            normalized = BrokerOrderSnapshot(
                broker_order_id=receipt.broker_order_id,
                intent_id=receipt.intent_id,
                status=str(receipt.payload.get("status", "UNKNOWN")),
                filled_quantity=receipt.cumulative_filled_quantity,
                requested_quantity=int(receipt.payload.get("requested_quantity", receipt.quantity or 1)),
            )
            self._seen[receipt.event_id] = normalized
            return (normalized,)
        raise ValueError(f"unsupported broker receipt kind: {receipt.kind}")

    def cumulative_quantity(self, broker_order_id: str) -> int:
        return self._cumulative.get(broker_order_id, 0)

    def fills_for_order(self, broker_order_id: str) -> tuple[BrokerFill, ...]:
        return tuple(self._fills.get(broker_order_id, ()))
