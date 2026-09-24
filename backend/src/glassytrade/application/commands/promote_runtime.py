"""One-shot runtime promotion command; never performs broker writes itself."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass(frozen=True)
class PromotionResult:
    allowed: bool
    executed: bool
    target_release_id: str


def promote_runtime(plan: Mapping[str, Any], *, execute: bool) -> PromotionResult:
    target = str(plan.get("target_release_id", ""))
    if not target:
        raise ValueError("promotion plan has no target release")
    if execute and plan.get("approved") is not True:
        raise ValueError("promotion execution requires an approved plan")
    return PromotionResult(allowed=True, executed=execute, target_release_id=target)
