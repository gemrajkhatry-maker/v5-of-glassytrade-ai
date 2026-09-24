"""Read-only journal query."""

from __future__ import annotations

from typing import Protocol

from glassytrade.domain.ledger.events import LedgerEvent


class JournalQuery(Protocol):
    def read_after(self, sequence: int) -> tuple[LedgerEvent, ...]: ...


class JournalQueryService:
    def __init__(self, source: JournalQuery) -> None:
        self.source = source

    def get(self, after_sequence: int = 0) -> tuple[LedgerEvent, ...]:
        return self.source.read_after(after_sequence)
