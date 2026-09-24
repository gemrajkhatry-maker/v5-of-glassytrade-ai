"""Broker execution port and normalized transport values."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import AsyncIterator, Protocol, TypeAlias

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import (
    BrokerAck,
    BrokerCapabilities,
    BrokerFill,
    BrokerLookupStatus,
    BrokerOrderSnapshot,
    OrderSide,
)


@dataclass(frozen=True)
class BrokerPlaceRequest:
    attempt_id: str
    contract_id: ContractId
    side: OrderSide
    quantity: int
    correlation_id: str
    reference_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.correlation_id:
            raise ValueError("attempt_id and correlation_id are required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True)
class BrokerCancelRequest:
    broker_order_id: str
    correlation_id: str
    reason: str


@dataclass(frozen=True)
class BrokerReplaceRequest:
    broker_order_id: str
    correlation_id: str
    quantity: int
    reference_price: Decimal | None = None


@dataclass(frozen=True)
class BrokerLookupResult:
    status: BrokerLookupStatus
    order: BrokerOrderSnapshot | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", BrokerLookupStatus(self.status))
        if self.status is BrokerLookupStatus.FOUND and self.order is None:
            raise ValueError("FOUND lookup requires an order")


BrokerPlaceResult: TypeAlias = BrokerAck
BrokerCancelResult: TypeAlias = BrokerAck
BrokerReplaceResult: TypeAlias = BrokerAck
BrokerEvent: TypeAlias = BrokerFill | BrokerOrderSnapshot


class BrokerExecutionPort(Protocol):
    @property
    def capabilities(self) -> BrokerCapabilities: ...

    def place_order(self, request: BrokerPlaceRequest) -> BrokerPlaceResult: ...

    def cancel_order(self, request: BrokerCancelRequest) -> BrokerCancelResult: ...

    def replace_order(self, request: BrokerReplaceRequest) -> BrokerReplaceResult: ...

    def get_order(self, broker_order_id: str) -> BrokerLookupResult: ...

    def find_order_by_correlation(self, correlation_id: str) -> BrokerLookupResult: ...

    def list_orders(self) -> tuple[BrokerOrderSnapshot, ...]: ...

    def list_fills(self) -> tuple[BrokerFill, ...]: ...

    def list_positions(self) -> tuple[object, ...]: ...

    def stream_events(self) -> AsyncIterator[BrokerEvent]: ...
