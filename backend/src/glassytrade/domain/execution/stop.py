"""Pure protective-stop state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.common.money import to_decimal


class StopState(StrEnum):
    REQUIRED = "REQUIRED"
    PREPARED = "PREPARED"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    REPLACING = "REPLACING"
    RETIRED = "RETIRED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


@dataclass(frozen=True)
class ProtectionRequired:
    protection_id: str
    position_id: str
    contract_id: ContractId
    quantity: int
    desired_stop: Decimal
    state: StopState = StopState.REQUIRED
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.protection_id or not self.position_id:
            raise ValueError("protection and position IDs are required")
        if self.quantity <= 0:
            raise ValueError("protection quantity must be positive")
        object.__setattr__(self, "desired_stop", to_decimal(self.desired_stop))
        object.__setattr__(self, "state", StopState(self.state))


@dataclass(frozen=True)
class StopOrder:
    stop_id: str
    protection_id: str
    desired_stop: Decimal
    effective_stop: Decimal | None
    quantity: int
    state: StopState
    broker_order_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "desired_stop", to_decimal(self.desired_stop))
        if self.effective_stop is not None:
            object.__setattr__(self, "effective_stop", to_decimal(self.effective_stop))
        if self.quantity <= 0:
            raise ValueError("stop quantity must be positive")
        object.__setattr__(self, "state", StopState(self.state))


_TRANSITIONS = {
    StopState.REQUIRED: frozenset({StopState.PREPARED, StopState.FAILED}),
    StopState.PREPARED: frozenset({StopState.ACTIVATING, StopState.UNKNOWN, StopState.FAILED}),
    StopState.ACTIVATING: frozenset({StopState.ACTIVE, StopState.UNKNOWN, StopState.FAILED}),
    StopState.ACTIVE: frozenset({StopState.REPLACING, StopState.RETIRED, StopState.UNKNOWN}),
    StopState.REPLACING: frozenset({StopState.ACTIVE, StopState.UNKNOWN, StopState.FAILED, StopState.RETIRED}),
    StopState.UNKNOWN: frozenset({StopState.RECONCILIATION_REQUIRED}),
    StopState.RECONCILIATION_REQUIRED: frozenset(),
    StopState.RETIRED: frozenset(),
    StopState.FAILED: frozenset(),
}


def transition_stop_state(current: StopState, target: StopState) -> StopState:
    current = StopState(current)
    target = StopState(target)
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"invalid stop transition: {current} -> {target}")
    return target
