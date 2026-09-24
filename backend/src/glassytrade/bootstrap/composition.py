"""Composition root for the target runtime; legacy remains the default elsewhere."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from glassytrade.adapters.persistence.sqlite.migrations import create_database
from glassytrade.application.oms.command_service import OmsCommandService
from glassytrade.application.oms.recovery_service import RecoveryService
from glassytrade.application.runtime.execution_coordinator import ExecutionCoordinator
from glassytrade.application.runtime.scanner import StaticScanner
from glassytrade.application.runtime.supervisor import RuntimeSupervisor
from glassytrade.bootstrap.runtime_config import RuntimeConfig
from glassytrade.domain.common.ids import ContractId


@dataclass(frozen=True)
class TargetRuntime:
    supervisor: RuntimeSupervisor
    coordinator: ExecutionCoordinator
    connection: Any


def build_target_runtime(
    config: RuntimeConfig,
    *,
    broker: Any | None = None,
    feed: Any | None = None,
    storage: Any | None = None,
    workers: Iterable[Any] = (),
    contracts: tuple[ContractId, ...] = (),
) -> TargetRuntime:
    if config.runtime_engine != "target":
        raise ValueError("target composition requires runtime_engine='target'")
    if config.mode == "shadow" and broker is not None:
        raise ValueError("shadow composition cannot receive a broker-write adapter")
    connection = create_database(config.database_path)
    oms = OmsCommandService(connection)
    coordinator = ExecutionCoordinator(oms, account_id=config.account_id)
    supervisor = RuntimeSupervisor(
        config=config,
        coordinator=coordinator,
        scanner=StaticScanner(contracts),
        workers=workers,
        recovery=RecoveryService(connection, broker=broker),
        storage=storage,
        broker=broker,
        feed=feed,
    )
    return TargetRuntime(supervisor, coordinator, connection)


def run_target_runtime(
    config: RuntimeConfig, tape: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any], ...]:
    """Run the deterministic target replay seam without broker side effects."""

    if config.runtime_engine != "target":
        raise ValueError("target replay requires runtime_engine='target'")
    output: list[dict[str, Any]] = []
    for item in tape:
        output.append(
            {
                "contract_id": str(item["contract_id"]),
                "price": str(item["price"]),
                "sequence": int(item["sequence"]),
            }
        )
    return tuple(output)
