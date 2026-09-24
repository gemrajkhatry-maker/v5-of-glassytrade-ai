"""Read-only history query."""

from __future__ import annotations

from typing import Any, Protocol


class HistoryQuery(Protocol):
    def get(self, contract_id: str) -> Any: ...


class HistoryQueryService:
    def __init__(self, source: HistoryQuery) -> None:
        self.source = source

    def get(self, contract_id: str) -> Any:
        return self.source.get(contract_id)
