"""Target runtime contract scanner seam."""

from __future__ import annotations

from typing import Protocol

from glassytrade.domain.common.ids import ContractId


class ScannerPort(Protocol):
    def scan(self) -> tuple[ContractId, ...]: ...

    def stop(self) -> None: ...


class StaticScanner:
    def __init__(self, contracts: tuple[ContractId, ...] = ()) -> None:
        self.contracts = tuple(contracts)
        self.stopped = False

    def scan(self) -> tuple[ContractId, ...]:
        return self.contracts

    def stop(self) -> None:
        self.stopped = True
