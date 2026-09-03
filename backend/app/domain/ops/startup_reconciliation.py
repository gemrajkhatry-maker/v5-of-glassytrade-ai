"""Startup Reconciliation — verifies DB positions against broker API.

Addresses Valentini audit finding #1: "No position recovery after crash.
No broker-side reconciliation — engine blindly trusts DB."

Compares DB-loaded positions against broker's actual open positions.
Handles three cases:
  1. Position in DB AND at broker → restore (normal)
  2. Position in DB but NOT at broker → stale, remove from DB
  3. Position at broker but NOT in DB → orphaned, register as external
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.async_boundary import ensure_sync_adapter_result
from quant.reconciliation_service import (
    ReconcilePolicy,
    canonical_key,
    extract_symbol,
    index_rows,
    reconcile_sets,
)

__all__ = [
    "ReconcilePolicy",
    "ReconciliationResult",
    "StartupReconciliation",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of startup reconciliation."""

    db_positions: int
    broker_positions: int
    restored: int
    stale_removed: int
    orphaned_registered: int
    discrepancies: list[str]


class StartupReconciliation:
    """Verifies DB positions against broker API at startup.

    Called once during engine startup, before any signals are generated.
    Ensures the engine's position state matches the broker's actual state.
    """

    def __init__(
        self,
        broker_adapter,
        storage,
        policy: ReconcilePolicy = ReconcilePolicy.QUARANTINE,
    ) -> None:
        self._broker = broker_adapter
        self._storage = storage
        self._policy = policy

    def reconcile(self) -> ReconciliationResult:
        """Run startup reconciliation.

        Returns ReconciliationResult with counts of restored/stale/orphaned positions.
        """
        discrepancies = []

        db_positions = []
        if self._storage:
            try:
                db_positions = ensure_sync_adapter_result(
                    "storage.load_open_positions",
                    self._storage.load_open_positions,
                )
                if db_positions is None:
                    db_positions = []
            except Exception as e:
                logger.error(
                    "Startup reconciliation: failed to load DB positions: %s", e
                )
                discrepancies.append(f"DB load failed: {e}")

        from app.shared.mode import is_live_mode

        if not is_live_mode():
            return ReconciliationResult(
                db_positions=len(db_positions),
                broker_positions=0,
                restored=len(db_positions),
                stale_removed=0,
                orphaned_registered=0,
                discrepancies=discrepancies,
            )

        # Query broker API for actual open positions
        broker_positions = []
        try:
            if hasattr(self._broker, "get_positions"):
                broker_positions = ensure_sync_adapter_result(
                    "broker.get_positions",
                    self._broker.get_positions,
                ) or []
            elif hasattr(self._broker, "get_account_positions"):
                broker_positions = ensure_sync_adapter_result(
                    "broker.get_account_positions",
                    self._broker.get_account_positions,
                ) or []
        except Exception as e:
            logger.warning(
                "Startup reconciliation: failed to query broker API: %s",
                e,
            )
            discrepancies.append(f"Broker API query failed: {e}")

        # Compare via the single reconciliation service (presence-only: the
        # DB startup path tracks presence, not sizes; journal plays no role
        # here — journal replay is QuantEngine.startup_reconcile's job).
        db_index = index_rows(db_positions)
        broker_index = index_rows(broker_positions)
        outcome = reconcile_sets(
            db_index, broker_index, {}, policy=self._policy
        )

        # Case 2 (DELETE_STALE opt-in): remove the stale rows the service
        # reported. QUARANTINE default reports no stale keys — no deletes.
        if self._storage:
            for key in outcome.stale_keys:
                for pos in db_positions:
                    if canonical_key(pos.get("symbol", "")) != key:
                        continue
                    try:
                        ensure_sync_adapter_result(
                            "storage.delete_open_position",
                            self._storage.delete_open_position,
                            pos.get("id", ""),
                        )
                    except (KeyError, TypeError):
                        logger.debug("Failed to delete stale open position: %s", pos.get("id"), exc_info=True)

        discrepancies.extend(outcome.discrepancies)

        logger.info(
            "Startup reconciliation: DB=%d broker=%d restored=%d stale=%d orphaned=%d",
            len(db_positions),
            len(broker_positions),
            outcome.restored,
            outcome.stale_removed,
            outcome.orphaned,
        )

        return ReconciliationResult(
            db_positions=len(db_positions),
            broker_positions=len(broker_positions),
            restored=outcome.restored,
            stale_removed=outcome.stale_removed,
            orphaned_registered=outcome.orphaned,
            discrepancies=discrepancies,
        )

    @staticmethod
    def _row_key(symbol: str) -> str:
        """Canonical compare key (delegates to the shared service)."""
        return canonical_key(symbol)

    @staticmethod
    def _extract_underlying(broker_position) -> str:
        """Extract symbol from broker position object (delegates to the service)."""
        return extract_symbol(broker_position)
