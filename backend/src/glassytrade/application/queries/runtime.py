"""Read-only runtime projection query."""

from __future__ import annotations

from typing import Any, Protocol


class RuntimeQuery(Protocol):
    def runtime_snapshot(self) -> dict[str, Any]: ...


class RuntimeQueryService:
    def __init__(self, source: RuntimeQuery) -> None:
        self.source = source

    def get(self) -> dict[str, Any]:
        return self.source.runtime_snapshot()
