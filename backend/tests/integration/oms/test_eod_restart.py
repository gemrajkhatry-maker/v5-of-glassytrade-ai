from datetime import datetime, timezone

from glassytrade.application.runtime.eod import EodService, EodState

NOW = datetime(2026, 9, 24, 15, 30, tzinfo=timezone.utc)


class Broker:
    def list_positions(self):
        return []

    def list_orders(self):
        return []

    def list_fills(self):
        return []


def test_eod_state_survives_service_reconstruction(tmp_path):
    state_path = tmp_path / "eod.json"
    service = EodService(Broker(), state_path=state_path)
    service.arm(("NSE", "2026-09-24"), NOW)
    resumed = EodService(Broker(), state_path=state_path)
    assert resumed.resume(("NSE", "2026-09-24")) is EodState.ENTRY_BLOCKED


def test_eod_state_resumes_after_restart_without_completion_shortcut():
    service = EodService(Broker())
    service.arm(("NSE", "2026-09-24"), NOW)
    assert service.resume(("NSE", "2026-09-24")) is EodState.ENTRY_BLOCKED
    assert service.advance(NOW).state is EodState.COMPLETE
    assert service.resume(("NSE", "2026-09-24")) is EodState.COMPLETE
