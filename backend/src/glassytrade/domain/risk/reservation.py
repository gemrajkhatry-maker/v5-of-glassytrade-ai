"""Atomic risk reservation and fill conversion rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from glassytrade.domain.execution.types import (
    Fill,
    Position,
    RiskReservation,
    RiskReservationStatus,
    RiskState,
)


@dataclass(frozen=True)
class EntryRiskRequest:
    intent_id: str
    owner: str
    risk_amount: Decimal


@dataclass(frozen=True)
class RiskPolicy:
    max_reserved_risk: Decimal
    max_daily_loss: Decimal = Decimal("Infinity")


@dataclass(frozen=True)
class ReservationDecision:
    accepted: bool
    state: RiskState
    reservation: RiskReservation | None = None
    reason: str | None = None


def reserve_entry(
    state: RiskState,
    request: EntryRiskRequest,
    policy: RiskPolicy,
) -> ReservationDecision:
    amount = Decimal(str(request.risk_amount))
    if amount <= 0:
        raise ValueError("risk_amount must be positive")
    if state.reserved_risk + amount > policy.max_reserved_risk:
        return ReservationDecision(False, state, reason="risk limit exceeded")
    reservation = RiskReservation(
        reservation_id=f"reservation:{request.intent_id}",
        intent_id=request.intent_id,
        owner=request.owner,
        amount=amount,
    )
    return ReservationDecision(
        True,
        replace(state, reserved_risk=state.reserved_risk + amount),
        reservation,
    )


def reserve_exit(
    position: Position,
    quantity: int,
    claims: tuple[RiskReservation, ...],
) -> ReservationDecision:
    if quantity <= 0 or abs(position.signed_quantity) < quantity:
        return ReservationDecision(False, RiskState("unknown"), reason="exit quantity exceeds position")
    open_claims = tuple(
        claim for claim in claims if claim.status is not RiskReservationStatus.RELEASED
    )
    state = RiskState(
        account_id=position.position_id,
        reserved_risk=sum((claim.amount for claim in open_claims), Decimal("0")),
    )
    return ReservationDecision(True, state, reason=None)


def apply_fill(
    state: RiskState,
    reservation: RiskReservation,
    fill: Fill,
) -> tuple[RiskState, RiskReservation]:
    if fill.intent_id != reservation.intent_id:
        raise ValueError("fill does not belong to reservation")
    if reservation.status is not RiskReservationStatus.RESERVED:
        raise ValueError("reservation is not open")
    committed = state.committed_risk + reservation.amount
    next_state = replace(
        state,
        reserved_risk=max(Decimal("0"), state.reserved_risk - reservation.amount),
        committed_risk=committed,
    )
    next_reservation = replace(reservation, status=RiskReservationStatus.COMMITTED)
    return next_state, next_reservation
