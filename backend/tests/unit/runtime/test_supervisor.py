from types import SimpleNamespace

from glassytrade.application.runtime.supervisor import RuntimeSupervisor
from glassytrade.domain.common.ids import ContractId


CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "s")


class FakeScanner:
    def __init__(self):
        self.stopped = False

    def scan(self):
        return (CONTRACT,)

    def stop(self):
        self.stopped = True


class FakeWorker:
    def __init__(self):
        self.stopped = False

    def start(self):
        return None

    def stop(self):
        self.stopped = True


class FakeStorage:
    def __init__(self):
        self.closed = False

    def flush(self):
        return None

    def close(self):
        self.closed = True


class FakePort:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeRecovery:
    def recover(self, request):
        return SimpleNamespace(
            journal_verified=True,
            rebuilt_sequence=0,
            account=SimpleNamespace(account_id="paper-main", positions=(), realized_pnl=0, last_sequence=0),
            risk=SimpleNamespace(),
            unresolved_cases=(),
            broker_snapshot_available=True,
            recovery_complete=True,
            runtime_ready=False,
        )


def test_supervisor_starts_workers_and_readiness_stays_degraded_until_later_gates(tmp_path):
    scanner = FakeScanner()
    storage = FakeStorage()
    broker = FakePort()
    feed = FakePort()
    supervisor = RuntimeSupervisor(
        config=SimpleNamespace(mode="paper", account_id="paper-main"),
        coordinator=SimpleNamespace(),
        scanner=scanner,
        workers=(),
        recovery=FakeRecovery(),
        storage=storage,
        broker=broker,
        feed=feed,
    )
    status = supervisor.start()
    assert status.started is True
    assert supervisor.readiness().status.value == "DEGRADED_NO_NEW_ENTRIES"
    assert supervisor.rescan() == (CONTRACT,)
    supervisor.stop("test", timeout_seconds=0.1)
    assert scanner.stopped is True
    assert storage.closed is True
    assert broker.closed is True
    assert feed.closed is True
