from decimal import Decimal

from glassytrade.domain.execution.types import RiskReservation, RiskReservationStatus, RiskState
from glassytrade.domain.risk.reservation import (
    EntryRiskRequest,
    RiskPolicy,
    apply_fill,
    reserve_entry,
)


def test_reserve_entry_rejects_when_policy_limit_is_exceeded():
    state = RiskState("paper", reserved_risk=Decimal("95"))
    request = EntryRiskRequest(
        intent_id="intent-1",
        owner="risk-authority",
        risk_amount=Decimal("10"),
    )
    policy = RiskPolicy(max_reserved_risk=Decimal("100"))
    decision = reserve_entry(state, request, policy)
    assert decision.accepted is False
    assert decision.reason == "risk limit exceeded"


def test_apply_fill_moves_reserved_risk_to_committed_risk():
    state = RiskState("paper")
    reservation = RiskReservation(
        reservation_id="res-1",
        intent_id="intent-1",
        owner="risk-authority",
        amount=Decimal("10"),
    )
    from datetime import datetime, timezone
    from glassytrade.domain.common.ids import ContractId
    from glassytrade.domain.execution.types import Fill

    fill = Fill(
        fill_id="fill-1",
        intent_id="intent-1",
        contract_id=ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s"),
        quantity=1,
        price=Decimal("100"),
        fees=Decimal("0"),
        filled_at=datetime.now(timezone.utc),
    )
    next_state, next_reservation = apply_fill(state, reservation, fill)
    assert next_state.committed_risk == Decimal("10")
    assert next_state.reserved_risk == Decimal("0")
    assert next_reservation.status is RiskReservationStatus.COMMITTED
