from datetime import datetime, timezone

from glassytrade.application.runtime.eod import EodService, EodState

NOW = datetime(2026, 9, 24, 15, 30, tzinfo=timezone.utc)
SESSION = ("NSE", "2026-09-24")


class Broker:
    def __init__(self):
        self.positions = []
        self.orders = []
        self.fills = []
        self.calls = 0

    def list_positions(self):
        self.calls += 1
        return self.positions

    def list_orders(self):
        self.calls += 1
        return self.orders

    def list_fills(self):
        self.calls += 1
        return self.fills


def test_eod_arm_does_not_call_broker():
    broker = Broker()
    service = EodService(broker)
    state = service.arm(SESSION, NOW)
    assert state is EodState.ENTRY_BLOCKED
    assert broker.calls == 0


def test_eod_completes_only_after_broker_flat():
    broker = Broker()
    service = EodService(broker)
    service.arm(SESSION, NOW)
    broker.positions = [{"contract_id": "NIFTY", "signed_quantity": 1}]
    assert service.advance(NOW).state is not EodState.COMPLETE
    broker.positions = []
    broker.orders = []
    assert service.advance(NOW).state is EodState.COMPLETE


def test_eod_resume_does_not_invent_completion():
    service = EodService(Broker())
    assert service.resume(SESSION) is EodState.IDLE
    service.arm(SESSION, NOW)
    assert service.resume(SESSION) is EodState.ENTRY_BLOCKED
    assert not hasattr(service, "complete")
