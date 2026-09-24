from datetime import datetime, timezone
from decimal import Decimal

from glassytrade.application.oms.protective_order_service import ProtectiveOrderService
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Fill

CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s")


def test_stop_exit_race_retires_only_after_exit_fill():
    service = ProtectiveOrderService()
    service.ensure_for_fill(
        Fill("f", "i", CONTRACT, 65, Decimal("100"), Decimal("0"), datetime.now(timezone.utc)),
        stop_price=Decimal("95"),
    )
    receipt = service.retire_for_exit(
        CONTRACT.key,
        Fill("exit", "i", CONTRACT, 65, Decimal("100"), Decimal("0"), datetime.now(timezone.utc)),
    )
    assert receipt.status.value == "RETIRED"
    assert service.verify(CONTRACT.key).protected_quantity == 0
