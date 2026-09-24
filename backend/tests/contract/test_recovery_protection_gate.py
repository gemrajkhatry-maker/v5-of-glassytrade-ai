from glassytrade.application.oms.protective_order_service import ProtectiveOrderService


def test_recovery_protection_gate_rejects_unverified_position():
    service = ProtectiveOrderService()
    service.set_position_quantity("NIFTY", 10)
    verification = service.verify("NIFTY")
    assert verification.verified is False
    assert verification.reason == "protection_missing"
