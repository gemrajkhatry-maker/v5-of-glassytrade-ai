"""Truthful readiness — distinguish degraded-no-new-entries from not-ready.

Phase 0.3 of the architecture refactor. The previous readiness check reported
'ok' or 'degraded' without distinguishing whether the system could accept new
trading entries. It also did not reflect paper position quarantine status.

This module defines the canonical readiness status and a function to compute it
from a QuantCoordinator-like object. The coordinator exposes a
`quarantined_positions()` method that returns the set of symbols currently
quarantined; crashed engines are reported via `crashed_engines()`.

Readiness status ladder (most severe wins):
- NOT_READY: crashed engines, coordinator not started, no coordinator at all
- DEGRADED_NO_NEW_ENTRIES: quarantined paper positions pending resolution
- READY: clean state
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class ReadinessStatus(str, Enum):
    """Canonical readiness outcomes for the trading system."""
    READY = "READY"
    DEGRADED_NO_NEW_ENTRIES = "DEGRADED_NO_NEW_ENTRIES"
    NOT_READY = "NOT_READY"


class CoordinatorLike(Protocol):
    """Structural type for the subset of QuantCoordinator readiness reads."""

    started: bool

    def crashed_engines(self) -> list[str]: ...
    def quarantined_positions(self) -> set[str]: ...


def readiness_status(
    coordinator: Any,
) -> tuple[ReadinessStatus, dict[str, str]]:
    """Compute readiness status from coordinator state.

    Returns a (status, details) tuple. Details includes each sub-check so
    callers can render diagnostics.

    The severity ladder is:
      NOT_READY > DEGRADED_NO_NEW_ENTRIES > READY
    Any single NOT_READY condition makes the whole system NOT_READY.
    """
    details: dict[str, str] = {}

    if coordinator is None:
        details["coordinator"] = "not_ready: no coordinator"
        return ReadinessStatus.NOT_READY, details

    if not bool(getattr(coordinator, "started", False)):
        details["coordinator"] = "not_ready: coordinator not_started"
        return ReadinessStatus.NOT_READY, details

    details["coordinator"] = "ok"

    # Crashed engines — NOT_READY
    crashed: list[str] = []
    try:
        crashed_fn = getattr(coordinator, "crashed_engines", None)
        crashed = list(crashed_fn() if callable(crashed_fn) else [])
    except Exception as exc:
        details["crashed_engines"] = f"error: {exc}"
        return ReadinessStatus.NOT_READY, details

    if crashed:
        details["crashed_engines"] = f"not_ready: {len(crashed)} crashed engine(s)"
        return ReadinessStatus.NOT_READY, details

    details["crashed_engines"] = "ok"

    # Quarantined paper positions — DEGRADED_NO_NEW_ENTRIES
    quarantined: set[str] = set()
    try:
        qp_fn = getattr(coordinator, "quarantined_positions", None)
        quarantined = set(qp_fn() if callable(qp_fn) else [])
    except Exception as exc:
        details["quarantined"] = f"error: {exc}"
        return ReadinessStatus.NOT_READY, details

    if quarantined:
        details["quarantined"] = (
            f"degraded_no_new_entries: {len(quarantined)} quarantined position(s): "
            f"{sorted(quarantined)}"
        )
        return ReadinessStatus.DEGRADED_NO_NEW_ENTRIES, details

    details["quarantined"] = "ok"
    return ReadinessStatus.READY, details
