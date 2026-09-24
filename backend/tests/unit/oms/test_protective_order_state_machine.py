from datetime import datetime, timezone
from decimal import Decimal

from glassytrade.application.oms.protective_order_service import ProtectiveOrderService
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Fill, ProtectionStatus

CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s")


def fill(quantity: int = 65) -> Fill:
    return Fill(
        fill_id=f"fill-{quantity}",
        intent_id="intent-1",
        contract_id=CONTRACT,
        quantity=quantity,
        price=Decimal("100"),
        fees=Decimal("0"),
        filled_at=datetime.now(timezone.utc),
    )


def test_partial_fill_protects_only_filled_quantity():
    service = ProtectiveOrderService()
    receipt = service.ensure_for_fill(fill(65), stop_price=Decimal("95"))
    assert receipt.protection_quantity == 65
    assert receipt.status is ProtectionStatus.PREPARED
    assert receipt.effective_stop is None


def test_ratchet_does_not_claim_effective_stop_without_confirmation():
    service = ProtectiveOrderService()
    first = service.ensure_for_fill(fill(65), stop_price=Decimal("95"))
    ratchet = service.ratchet(CONTRACT.key, Decimal("97"), "profit")
    assert ratchet.status is ProtectionStatus.REPLACING
    assert ratchet.effective_stop is None
    assert first.receipt_id != ratchet.receipt_id


def test_retire_and_verify_require_position_evidence():
    service = ProtectiveOrderService()
    receipt = service.ensure_for_fill(fill(65), stop_price=Decimal("95"))
    service.set_position_quantity(CONTRACT.key, 65)
    verification = service.verify(CONTRACT.key)
    assert verification.position_quantity == 65
    assert verification.protected_quantity == 65
    assert verification.verified is False
    service.retire_for_exit(CONTRACT.key, fill(65))
    assert service.verify(CONTRACT.key).protected_quantity == 0
    assert receipt.status is ProtectionStatus.PREPARED
