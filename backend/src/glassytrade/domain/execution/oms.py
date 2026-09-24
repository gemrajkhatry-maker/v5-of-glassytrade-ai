"""Pure OMS transition rules and command result values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from glassytrade.domain.execution.types import (
    ExecutionAttempt,
    ExecutionAttemptStatus,
    OrderIntent,
    OrderStatus,
    RiskReservation,
)


class OmsDomainError(RuntimeError):
    """Base error for invalid OMS state transitions."""


class InvalidTransition(OmsDomainError):
    """Raised when a terminal or invalid transition is requested."""


class ReconciliationRequired(OmsDomainError):
    """Raised when UNKNOWN state requires broker reconciliation."""


_ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.RESERVED, OrderStatus.REJECTED}),
    OrderStatus.RESERVED: frozenset({OrderStatus.READY, OrderStatus.REJECTED}),
    OrderStatus.READY: frozenset(
        {
            OrderStatus.WORKING_UNFILLED,
            OrderStatus.WORKING_PARTIAL,
            OrderStatus.COMPLETED,
            OrderStatus.NO_FILL,
            OrderStatus.REJECTED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.WORKING_UNFILLED: frozenset(
        {
            OrderStatus.WORKING_PARTIAL,
            OrderStatus.COMPLETED,
            OrderStatus.UNKNOWN,
            OrderStatus.RECONCILIATION_REQUIRED,
        }
    ),
    OrderStatus.WORKING_PARTIAL: frozenset(
        {OrderStatus.COMPLETED_PARTIAL, OrderStatus.UNKNOWN, OrderStatus.RECONCILIATION_REQUIRED}
    ),
    OrderStatus.UNKNOWN: frozenset({OrderStatus.RECONCILIATION_REQUIRED}),
    OrderStatus.RECONCILIATION_REQUIRED: frozenset(),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.COMPLETED_PARTIAL: frozenset(),
    OrderStatus.NO_FILL: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}

_ATTEMPT_TRANSITIONS: dict[ExecutionAttemptStatus, frozenset[ExecutionAttemptStatus]] = {
    ExecutionAttemptStatus.PREPARED: frozenset({ExecutionAttemptStatus.DISPATCHING}),
    ExecutionAttemptStatus.DISPATCHING: frozenset(
        {
            ExecutionAttemptStatus.OPEN,
            ExecutionAttemptStatus.PARTIAL,
            ExecutionAttemptStatus.FILLED,
            ExecutionAttemptStatus.REJECTED,
            ExecutionAttemptStatus.UNKNOWN,
        }
    ),
    ExecutionAttemptStatus.OPEN: frozenset(
        {
            ExecutionAttemptStatus.PARTIAL,
            ExecutionAttemptStatus.FILLED,
            ExecutionAttemptStatus.CANCELLED,
            ExecutionAttemptStatus.EXPIRED,
            ExecutionAttemptStatus.UNKNOWN,
        }
    ),
    ExecutionAttemptStatus.PARTIAL: frozenset(
        {
            ExecutionAttemptStatus.FILLED,
            ExecutionAttemptStatus.CANCELLED,
            ExecutionAttemptStatus.UNKNOWN,
        }
    ),
    ExecutionAttemptStatus.UNKNOWN: frozenset(),
    ExecutionAttemptStatus.FILLED: frozenset(),
    ExecutionAttemptStatus.REJECTED: frozenset(),
    ExecutionAttemptStatus.CANCELLED: frozenset(),
    ExecutionAttemptStatus.EXPIRED: frozenset(),
}


def transition_order_status(current: OrderStatus, target: OrderStatus) -> OrderStatus:
    current = OrderStatus(current)
    target = OrderStatus(target)
    if target not in _ORDER_TRANSITIONS[current]:
        raise InvalidTransition(f"invalid order transition: {current} -> {target}")
    return target


def transition_attempt_status(
    current: ExecutionAttemptStatus, target: ExecutionAttemptStatus
) -> ExecutionAttemptStatus:
    current = ExecutionAttemptStatus(current)
    target = ExecutionAttemptStatus(target)
    if target not in _ATTEMPT_TRANSITIONS[current]:
        if current is ExecutionAttemptStatus.UNKNOWN:
            raise ReconciliationRequired("unknown attempt requires reconciliation")
        raise InvalidTransition(f"invalid attempt transition: {current} -> {target}")
    return target


@dataclass(frozen=True)
class PreparedOrder:
    intent: OrderIntent
    attempt: ExecutionAttempt
    reservation: RiskReservation


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    receipt_id: str
    event_id: str | None = None
    normalized_event: Any | None = None


class ExecutionUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
