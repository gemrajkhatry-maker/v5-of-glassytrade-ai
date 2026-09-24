"""Readiness aggregation for the target runtime."""

from __future__ import annotations

from typing import Any

from glassytrade.domain.execution.types import Readiness, ReadinessStatus


def evaluate_readiness(
    *,
    started: bool,
    recovery_report: Any | None,
    feed_ready: bool = True,
    workers_ready: bool = True,
    protection_ready: bool = False,
    eod_ready: bool = False,
) -> Readiness:
    reasons: list[str] = []
    if not started:
        reasons.append("runtime_not_started")
    if recovery_report is None or not getattr(recovery_report, "journal_verified", False):
        reasons.append("journal_not_verified")
    if recovery_report is not None and getattr(recovery_report, "unresolved_cases", ()):
        reasons.append("reconciliation_cases_unresolved")
    if not feed_ready:
        reasons.append("feed_not_ready")
    if not workers_ready:
        reasons.append("workers_not_ready")
    if not protection_ready:
        reasons.append("protection_not_verified")
    if not eod_ready:
        reasons.append("eod_not_verified")
    if not reasons:
        return Readiness(ReadinessStatus.READY)
    if started and len(reasons) <= 2:
        return Readiness(ReadinessStatus.DEGRADED_NO_NEW_ENTRIES, tuple(reasons))
    return Readiness(ReadinessStatus.NOT_READY, tuple(reasons))
