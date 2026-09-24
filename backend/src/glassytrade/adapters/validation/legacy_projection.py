"""Read-only legacy projection adapter for shadow comparisons."""

from __future__ import annotations

from typing import Any, Mapping


class LegacyProjectionAdapter:
    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        self._snapshot = dict(snapshot)

    def read(self) -> dict[str, Any]:
        return dict(self._snapshot)

    def broker_write_capability(self) -> bool:
        return False
