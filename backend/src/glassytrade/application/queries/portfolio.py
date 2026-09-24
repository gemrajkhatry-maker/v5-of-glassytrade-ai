"""Read-only account projection query."""

from __future__ import annotations

from typing import Any, Protocol


class PortfolioQuery(Protocol):
    def project_account(self, account_id: str, *, after_sequence: int = 0) -> Any: ...


class PortfolioQueryService:
    def __init__(self, source: PortfolioQuery) -> None:
        self.source = source

    def get(self, account_id: str, *, after_sequence: int = 0) -> Any:
        return self.source.project_account(account_id, after_sequence=after_sequence)
