"""Paper position reconciliation — classify persisted positions against the active universe.

Phase 0.2 of the architecture refactor. The previous _spawn_engine loaded ALL
open positions from storage and restored any row matching the spawned symbol,
including positions for contracts no longer in the active universe. This
produced unmanaged positions sitting in the engine's book with no quotes, no
AMT, and no exits.

This module classifies every persisted position:
- OPEN: contract is in the active universe — restore into its engine.
- QUARANTINED_STALE_CONTRACT: contract not in the active universe — preserve
  in storage but do NOT restore into any engine.
- QUARANTINED_UNRESOLVED: unparseable or empty identity — preserve in storage
  but do NOT restore.

Quarantine is deliberate: auto-deleting stale rows would destroy the audit
trail, and silently restoring them would let unmanaged positions leak into
the run loop. Preservation without restore is the correct middle ground.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PaperPositionStatus(str, Enum):
    """Classification of a persisted paper position against the active universe."""
    OPEN = "OPEN"
    QUARANTINED_STALE_CONTRACT = "QUARANTINED_STALE_CONTRACT"
    QUARANTINED_UNRESOLVED = "QUARANTINED_UNRESOLVED"


@dataclass
class QuarantinedPosition:
    """A persisted position that should NOT be restored into any engine."""
    status: PaperPositionStatus
    symbol: str
    row: dict[str, Any]
    reason: str = ""


@dataclass
class ReconciliationResult:
    """Outcome of reconciling all persisted positions against the active universe."""
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    quarantined: list[QuarantinedPosition] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        """Compact summary for readiness checks and telemetry."""
        stale = sum(
            1 for q in self.quarantined
            if q.status == PaperPositionStatus.QUARANTINED_STALE_CONTRACT
        )
        unresolved = sum(
            1 for q in self.quarantined
            if q.status == PaperPositionStatus.QUARANTINED_UNRESOLVED
        )
        return {
            "open": len(self.open_positions),
            "quarantined_stale": stale,
            "quarantined_unresolved": unresolved,
            "total_persisted": len(self.open_positions) + len(self.quarantined),
        }


class PaperPositionReconciler:
    """Classify every persisted paper position against the active universe.

    Usage:
        reconciler = PaperPositionReconciler(storage, active_universe={"NIFTY 1 SEP 24200 CALL"})
        result = reconciler.reconcile()
        # result.open_positions — pass to engine.restore_position()
        # result.quarantined — leave in storage, do not restore
    """

    def __init__(
        self,
        storage: Any,
        active_universe: set[str] | None = None,
    ) -> None:
        self._storage = storage
        self._active = set(active_universe or set())

    def reconcile(self) -> ReconciliationResult:
        """Load all persisted positions and classify each one."""
        result = ReconciliationResult()
        if self._storage is None:
            return result
        rows: list[dict[str, Any]] = []
        try:
            rows = self._storage.load_open_positions() or []
        except Exception:
            # Storage failure — nothing can be safely restored.
            return result
        for row in rows:
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                result.quarantined.append(QuarantinedPosition(
                    status=PaperPositionStatus.QUARANTINED_UNRESOLVED,
                    symbol="",
                    row=row,
                    reason="unresolved position identity — empty or missing symbol",
                ))
                continue
            if symbol in self._active:
                result.open_positions.append(row)
            else:
                result.quarantined.append(QuarantinedPosition(
                    status=PaperPositionStatus.QUARANTINED_STALE_CONTRACT,
                    symbol=symbol,
                    row=row,
                    reason=f"contract {symbol!r} not in active universe",
                ))
        return result


def reconcile_paper_positions(
    storage: Any,
    active_universe: set[str] | None = None,
) -> ReconciliationResult:
    """Convenience wrapper — classify all persisted paper positions.

    Reconciles persisted positions against the active contract universe and
    returns a ReconciliationResult separating restorable positions from
    quarantined ones.
    """
    return PaperPositionReconciler(storage, active_universe).reconcile()
