from datetime import datetime, timezone
from decimal import Decimal

from glassytrade.application.oms.protective_order_service import ProtectiveOrderService
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Fill, ProtectionStatus

CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s")


def make_fill(quantity):
    return Fill("f", "i", CONTRACT, quantity, Decimal("100"), Decimal("0"), datetime.now(timezone.utc))


def test_stop_replacement_is_durable_before_broker_activation():
    service = ProtectiveOrderService()
    first = service.ensure_for_fill(make_fill(65), stop_price=Decimal("95"))
    replacement = service.ratchet(CONTRACT.key, Decimal("97"), "ratchet")
    assert replacement.status is ProtectionStatus.REPLACING
    assert first.effective_stop is None
    assert replacement.broker_order_id is None
