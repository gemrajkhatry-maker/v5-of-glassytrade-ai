from types import SimpleNamespace

from glassytrade.application.runtime.supervisor import RuntimeSupervisor


class Component:
    def __init__(self):
        self.events = []

    def close(self):
        self.events.append("close")

    def stop(self):
        self.events.append("stop")

    def flush(self):
        self.events.append("flush")


class Scanner(Component):
    def scan(self):
        return ()


class Recovery:
    def recover(self, request):
        return SimpleNamespace(
            journal_verified=True,
            rebuilt_sequence=0,
            account=SimpleNamespace(account_id="paper", positions=(), realized_pnl=0, last_sequence=0),
            risk=SimpleNamespace(),
            unresolved_cases=(),
            broker_snapshot_available=True,
            recovery_complete=True,
            runtime_ready=False,
        )


def test_supervisor_stop_order_blocks_new_risk_before_closing_dependencies(tmp_path):
    scanner = Scanner()
    storage = Component()
    broker = Component()
    feed = Component()
    supervisor = RuntimeSupervisor(
        config=SimpleNamespace(mode="paper", account_id="paper"),
        coordinator=SimpleNamespace(),
        scanner=scanner,
        workers=(),
        recovery=Recovery(),
        storage=storage,
        broker=broker,
        feed=feed,
    )
    supervisor.start()
    supervisor.stop("test", timeout_seconds=0.1)
    assert scanner.events == ["stop"]
    assert storage.events == ["flush", "close"]
    assert broker.events == ["close"]
    assert feed.events == ["close"]
    assert supervisor.accepting_orders is False
