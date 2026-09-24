"""Read-only shadow comparison seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ComparisonReport:
    matches: bool
    differences: tuple[str, ...]


class ShadowRunner:
    def __init__(self, broker: Any | None) -> None:
        self.broker = broker
        self.broker_write_capability = False

    def compare(
        self,
        legacy_snapshot: Mapping[str, Any],
        target_snapshot: Mapping[str, Any],
    ) -> ComparisonReport:
        differences: list[str] = []
        for key in sorted(set(legacy_snapshot) | set(target_snapshot)):
            if legacy_snapshot.get(key) != target_snapshot.get(key):
                differences.append(key)
        return ComparisonReport(not differences, tuple(differences))
