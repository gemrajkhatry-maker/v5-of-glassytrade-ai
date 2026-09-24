"""Supervisor owning target runtime lifecycle and dependency ordering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from glassytrade.application.runtime.readiness import evaluate_readiness
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import Readiness


@dataclass(frozen=True)
class RuntimeStatus:
    started: bool
    accepting_orders: bool
    worker_count: int
    recovery_complete: bool


class RuntimeSupervisor:
    def __init__(
        self,
        *,
        config: Any,
        coordinator: Any,
        scanner: Any,
        workers: Iterable[Any],
        recovery: Any,
        storage: Any = None,
        broker: Any = None,
        feed: Any = None,
    ) -> None:
        self.config = config
        self.coordinator = coordinator
        self.scanner = scanner
        self.workers = tuple(workers)
        self.recovery = recovery
        self.storage = storage
        self.broker = broker
        self.feed = feed
        self.started = False
        self.accepting_orders = False
        self.active_contracts: tuple[ContractId, ...] = ()
        self.recovery_report: Any | None = None

    def start(self) -> RuntimeStatus:
        if self.started:
            return self.status()
        from glassytrade.application.oms.recovery_service import RecoveryRequest

        self.recovery_report = self.recovery.recover(
            RecoveryRequest(
                session_key=f"{getattr(self.config, 'exchange', 'UNKNOWN')}:startup",
                account_id=getattr(self.config, "account_id", "unknown"),
            )
        )
        for worker in self.workers:
            start = getattr(worker, "start", None)
            if callable(start):
                start()
        self.active_contracts = tuple(self.scanner.scan())
        self.started = True
        self.accepting_orders = bool(
            getattr(self.recovery_report, "recovery_complete", False)
            and not getattr(self.recovery_report, "unresolved_cases", ())
        )
        return self.status()

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            started=self.started,
            accepting_orders=self.accepting_orders,
            worker_count=len(self.workers),
            recovery_complete=bool(
                self.recovery_report is not None
                and getattr(self.recovery_report, "recovery_complete", False)
            ),
        )

    def readiness(self) -> Readiness:
        return evaluate_readiness(
            started=self.started,
            recovery_report=self.recovery_report,
            workers_ready=all(
                getattr(worker, "worker_state", lambda: None)().running
                if callable(getattr(worker, "worker_state", None))
                else True
                for worker in self.workers
            ),
        )

    def rescan(self) -> tuple[ContractId, ...]:
        self.active_contracts = tuple(self.scanner.scan())
        return self.active_contracts

    def stop(self, reason: str, timeout_seconds: float = 10.0) -> None:
        self.accepting_orders = False
        scanner_stop = getattr(self.scanner, "stop", None)
        if callable(scanner_stop):
            scanner_stop()
        for worker in self.workers:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                stop()
        drain = getattr(self.coordinator, "drain", None)
        if callable(drain):
            drain()
        for dependency in (self.storage,):
            if dependency is None:
                continue
            for method_name in ("flush", "close"):
                method = getattr(dependency, method_name, None)
                if callable(method):
                    method()
        for dependency in (self.broker, self.feed):
            if dependency is None:
                continue
            close = getattr(dependency, "close", None)
            if callable(close):
                close()
        self.started = False
