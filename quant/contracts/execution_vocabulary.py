"""Broker-neutral execution vocabulary owned by the domain."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ExecutionStatus(str, Enum):
    INTENT_CREATED = "INTENT_CREATED"
    SUBMITTING = "SUBMITTING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RECONCILED = "RECONCILED"


@dataclass(frozen=True)
class ContractRef:
    symbol: str
    exchange: str
    instrument_type: str


@dataclass(frozen=True)
class EconomicOperationId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("economic operation identity is required")


@dataclass(frozen=True)
class OrderIntent:
    operation_id: EconomicOperationId
    contract: ContractRef
    side: str
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not isinstance(self.quantity, Decimal):
            raise TypeError("quantity must be Decimal")


@dataclass(frozen=True)
class ExecutionAttempt:
    intent: OrderIntent
    attempt_id: str

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("transport attempt identity is required")


@dataclass(frozen=True)
class Fill:
    operation_id: EconomicOperationId
    quantity: Decimal
    price: Decimal
    status: ExecutionStatus


@dataclass(frozen=True)
class ExposureState:
    symbol: str
    quantity: Decimal
    average_price: Decimal
