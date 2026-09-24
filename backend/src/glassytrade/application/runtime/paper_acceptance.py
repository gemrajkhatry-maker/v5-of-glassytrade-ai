"""Evidence-only paper session acceptance gate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Any


@dataclass(frozen=True)
class PaperAcceptanceReport:
    accepted: bool
    evidence: Mapping[str, Any]
    reasons: tuple[str, ...]


def evaluate_paper_acceptance(evidence: Mapping[str, Any]) -> PaperAcceptanceReport:
    reasons: list[str] = []
    for key in ("session_complete", "eod_verified", "reconciliation_clean"):
        if evidence.get(key) is not True:
            reasons.append(f"{key}_not_proven")
    if int(evidence.get("unresolved_cases", 0)) != 0:
        reasons.append("unresolved_reconciliation_cases")
    max_loss = Decimal(str(evidence.get("max_loss", "0")))
    loss_limit = Decimal(str(evidence.get("loss_limit", "0")))
    if loss_limit <= 0 or max_loss > loss_limit:
        reasons.append("loss_limit_not_proven")
    return PaperAcceptanceReport(not reasons, dict(evidence), tuple(reasons))
