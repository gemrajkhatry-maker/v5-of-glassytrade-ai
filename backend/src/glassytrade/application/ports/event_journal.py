"""Durable event journal port."""

from __future__ import annotations

from typing import Protocol

from glassytrade.domain.ledger.events import LedgerEvent


class EventJournal(Protocol):
    def append(self, event: LedgerEvent) -> None: ...

    def read_after(self, sequence: int) -> tuple[LedgerEvent, ...]: ...

    def verify(self) -> None: ...


ExecutionJournal = EventJournal
