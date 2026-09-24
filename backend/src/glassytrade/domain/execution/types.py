"""Canonical execution, risk, readiness, and broker contract values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeAlias

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.common.money import to_decimal


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderPurpose(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    STOP = "STOP"
    EMERGENCY = "EMERGENCY"


class OrderStatus(StrEnum):
    NEW = "NEW"
    RESERVED = "RESERVED"
    READY = "READY"
    WORKING_UNFILLED = "WORKING_UNFILLED"
    WORKING_PARTIAL = "WORKING_PARTIAL"
    COMPLETED = "COMPLETED"
    COMPLETED_PARTIAL = "COMPLETED_PARTIAL"
    NO_FILL = "NO_FILL"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ExecutionAttemptStatus(StrEnum):
    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ExposureState(StrEnum):
    FLAT = "FLAT"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class RiskReservationStatus(StrEnum):
    RESERVED = "RESERVED"
    PARTIALLY_CONVERTED = "PARTIALLY_CONVERTED"
    COMMITTED = "COMMITTED"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    RELEASED = "RELEASED"


class ReadinessStatus(StrEnum):
    READY = "READY"
    DEGRADED_NO_NEW_ENTRIES = "DEGRADED_NO_NEW_ENTRIES"
    NOT_READY = "NOT_READY"


class ProtectionStatus(StrEnum):
    PREPARED = "PREPARED"
    ACTIVE = "ACTIVE"
    REPLACING = "REPLACING"
    RETIRED = "RETIRED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class BrokerLookupStatus(StrEnum):
    FOUND = "FOUND"
    CONFIRMED_ABSENT = "CONFIRMED_ABSENT"
    UNAVAILABLE = "UNAVAILABLE"


class BrokerUnavailable(RuntimeError):
    """Raised when broker state cannot be fetched."""


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_quantity(value: int, name: str, *, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {qualifier} integer")


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    idempotency_key: str
    contract_id: ContractId
    purpose: str
    side: str
    requested_quantity: int
    reference_price: Decimal | None
    stop_price: Decimal | None
    target_price: Decimal | None

    def __post_init__(self) -> None:
        _require_text(self.intent_id, "intent_id")
        _require_text(self.idempotency_key, "idempotency_key")
        _require_text(self.purpose, "purpose")
        if self.side not in {side.value for side in OrderSide}:
            raise ValueError("side must be BUY or SELL")
        _require_quantity(self.requested_quantity, "requested_quantity")
        for name in ("reference_price", "stop_price", "target_price"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, to_decimal(value))


@dataclass(frozen=True)
class ExecutionAttempt:
    attempt_id: str
    intent_id: str
    requested_quantity: int
    status: ExecutionAttemptStatus = ExecutionAttemptStatus.PREPARED
    broker_order_id: str | None = None
    correlation_id: str = ""
    prepared_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.intent_id, "intent_id")
        if self.attempt_id == self.intent_id:
            raise ValueError("attempt_id and intent_id must be distinct")
        _require_quantity(self.requested_quantity, "requested_quantity")
        object.__setattr__(self, "status", ExecutionAttemptStatus(self.status))
        if not self.correlation_id:
            object.__setattr__(self, "correlation_id", self.attempt_id)
        if self.prepared_at is not None:
            _aware(self.prepared_at, "prepared_at")


@dataclass(frozen=True)
class Fill:
    fill_id: str
    intent_id: str
    contract_id: ContractId
    quantity: int
    price: Decimal
    fees: Decimal
    filled_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.fill_id, "fill_id")
        _require_text(self.intent_id, "intent_id")
        _require_quantity(self.quantity, "quantity")
        object.__setattr__(self, "price", to_decimal(self.price))
        object.__setattr__(self, "fees", to_decimal(self.fees))
        if self.price < 0 or self.fees < 0:
            raise ValueError("fill price and fees must be non-negative")
        _aware(self.filled_at, "filled_at")


@dataclass(frozen=True)
class Position:
    position_id: str
    contract_id: ContractId
    signed_quantity: int
    average_entry: Decimal
    current_stop: Decimal | None
    state: ExposureState = ExposureState.FLAT
    parent_position_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.position_id, "position_id")
        if not isinstance(self.signed_quantity, int) or isinstance(self.signed_quantity, bool):
            raise ValueError("signed_quantity must be an integer")
        object.__setattr__(self, "average_entry", to_decimal(self.average_entry))
        if self.current_stop is not None:
            object.__setattr__(self, "current_stop", to_decimal(self.current_stop))
            if self.current_stop < 0:
                raise ValueError("current_stop must be non-negative")
        object.__setattr__(self, "state", ExposureState(self.state))


@dataclass(frozen=True)
class RiskState:
    account_id: str
    reserved_risk: Decimal = Decimal("0")
    committed_risk: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    daily_loss: Decimal = Decimal("0")
    consecutive_losses: int = 0
    kill_switch: bool = False

    def __post_init__(self) -> None:
        _require_text(self.account_id, "account_id")
        for name in ("reserved_risk", "committed_risk", "realized_pnl", "daily_loss"):
            object.__setattr__(self, name, to_decimal(getattr(self, name)))
        if self.reserved_risk < 0 or self.committed_risk < 0 or self.daily_loss < 0:
            raise ValueError("risk amounts must be non-negative")
        _require_quantity(self.consecutive_losses, "consecutive_losses", allow_zero=True)


@dataclass(frozen=True)
class RiskReservation:
    reservation_id: str
    intent_id: str
    owner: str
    amount: Decimal
    status: RiskReservationStatus = RiskReservationStatus.RESERVED
    released_amount: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _require_text(self.reservation_id, "reservation_id")
        _require_text(self.intent_id, "intent_id")
        _require_text(self.owner, "owner")
        object.__setattr__(self, "amount", to_decimal(self.amount))
        object.__setattr__(self, "released_amount", to_decimal(self.released_amount))
        if self.amount < 0 or self.released_amount < 0 or self.released_amount > self.amount:
            raise ValueError("reservation amounts are invalid")
        object.__setattr__(self, "status", RiskReservationStatus(self.status))


@dataclass(frozen=True)
class IntentReceipt:
    receipt_id: str
    intent_id: str
    accepted_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_text(self.receipt_id, "receipt_id")
        _require_text(self.intent_id, "intent_id")
        _require_text(self.idempotency_key, "idempotency_key")
        _aware(self.accepted_at, "accepted_at")


@dataclass(frozen=True)
class ProtectionReceipt:
    receipt_id: str
    position_id: str
    status: ProtectionStatus
    desired_stop: Decimal
    effective_stop: Decimal | None
    broker_order_id: str | None
    protection_quantity: int = 0

    def __post_init__(self) -> None:
        _require_text(self.receipt_id, "receipt_id")
        _require_text(self.position_id, "position_id")
        object.__setattr__(self, "status", ProtectionStatus(self.status))
        object.__setattr__(self, "desired_stop", to_decimal(self.desired_stop))
        if self.effective_stop is not None:
            object.__setattr__(self, "effective_stop", to_decimal(self.effective_stop))
        _require_quantity(self.protection_quantity, "protection_quantity", allow_zero=True)


@dataclass(frozen=True)
class ExitReceipt:
    receipt_id: str
    position_id: str
    intent_id: str
    exit_fill_id: str
    closed_quantity: int
    received_at: datetime

    def __post_init__(self) -> None:
        for name in ("receipt_id", "position_id", "intent_id", "exit_fill_id"):
            _require_text(getattr(self, name), name)
        _require_quantity(self.closed_quantity, "closed_quantity")
        _aware(self.received_at, "received_at")


@dataclass(frozen=True)
class Readiness:
    status: ReadinessStatus
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ReadinessStatus(self.status))
        object.__setattr__(self, "reasons", tuple(self.reasons))
        if self.status is ReadinessStatus.READY and self.reasons:
            raise ValueError("READY readiness cannot contain blocking reasons")
        if self.status is not ReadinessStatus.READY and not self.reasons:
            raise ValueError("non-ready readiness requires reasons")

    @property
    def can_open_new_entries(self) -> bool:
        return self.status is ReadinessStatus.READY


@dataclass(frozen=True)
class BrokerCapabilities:
    names: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", frozenset(str(name) for name in self.names))

    def supports(self, name: str) -> bool:
        return name in self.names

    def __contains__(self, name: object) -> bool:
        return str(name) in self.names


@dataclass(frozen=True)
class Accepted:
    attempt_id: str
    broker_order_id: str
    acknowledged_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.broker_order_id, "broker_order_id")
        _aware(self.acknowledged_at, "acknowledged_at")


@dataclass(frozen=True)
class Rejected:
    attempt_id: str
    reason: str
    broker_code: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.reason, "reason")


@dataclass(frozen=True)
class NotSent:
    reason: str
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.reason, "reason")


@dataclass(frozen=True)
class AmbiguousOutcome:
    reason: str
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.reason, "reason")


@dataclass(frozen=True)
class StatusUnavailable:
    reason: str
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.reason, "reason")


BrokerAck: TypeAlias = Accepted | Rejected | NotSent | AmbiguousOutcome | StatusUnavailable


@dataclass(frozen=True)
class BrokerOrderSnapshot:
    broker_order_id: str
    intent_id: str
    status: str
    filled_quantity: int
    requested_quantity: int

    def __post_init__(self) -> None:
        for name in ("broker_order_id", "intent_id", "status"):
            _require_text(getattr(self, name), name)
        _require_quantity(self.filled_quantity, "filled_quantity", allow_zero=True)
        _require_quantity(self.requested_quantity, "requested_quantity")
        if self.filled_quantity > self.requested_quantity:
            raise ValueError("filled quantity cannot exceed requested quantity")


@dataclass(frozen=True)
class BrokerFill:
    broker_fill_id: str
    broker_order_id: str
    intent_id: str
    quantity: int
    price: Decimal
    fees: Decimal
    filled_at: datetime
    cumulative_filled_quantity: int = 0

    def __post_init__(self) -> None:
        for name in ("broker_fill_id", "broker_order_id", "intent_id"):
            _require_text(getattr(self, name), name)
        _require_quantity(self.quantity, "quantity")
        object.__setattr__(self, "price", to_decimal(self.price))
        object.__setattr__(self, "fees", to_decimal(self.fees))
        _require_quantity(self.cumulative_filled_quantity, "cumulative_filled_quantity", allow_zero=True)
        _aware(self.filled_at, "filled_at")
        if self.price < 0 or self.fees < 0:
            raise ValueError("broker fill price and fees must be non-negative")


@dataclass(frozen=True)
class ReconciliationReport:
    ready: bool
    checked_contracts: int
    discrepancies: tuple[str, ...] = ()
    unknown_attempts: tuple[ExecutionAttempt, ...] = ()
    open_reservations: tuple[RiskReservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.checked_contracts, int) or self.checked_contracts < 0:
            raise ValueError("checked_contracts must be non-negative")
        object.__setattr__(self, "discrepancies", tuple(self.discrepancies))
        object.__setattr__(self, "unknown_attempts", tuple(self.unknown_attempts))
        object.__setattr__(self, "open_reservations", tuple(self.open_reservations))
        if self.ready and self.discrepancies:
            raise ValueError("ready reconciliation cannot contain discrepancies")


@dataclass(frozen=True)
class MigrationManifest:
    release_id: str
    source: str
    target: str
    checksum: str
    started_at: datetime
    completed_at: datetime | None = None
    row_counts: Mapping[str, int] = MappingProxyType({})

    def __post_init__(self) -> None:
        for name in ("release_id", "source", "target", "checksum"):
            _require_text(getattr(self, name), name)
        _aware(self.started_at, "started_at")
        if self.completed_at is not None:
            _aware(self.completed_at, "completed_at")
        object.__setattr__(self, "row_counts", MappingProxyType(dict(self.row_counts)))
        if any(not isinstance(count, int) or count < 0 for count in self.row_counts.values()):
            raise ValueError("migration row counts must be non-negative integers")
