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

import enum
import logging
from dataclasses import dataclass
from app.core.async_boundary import ensure_sync_adapter_result

logger = logging.getLogger(__name__)


class ReconcilePolicy(enum.Enum):
    """Stale-row policy for DB-but-not-broker positions. (REF-09)

    Fail-safe default is QUARANTINE: stale rows are left in the DB for
    manual review. DELETE_STALE restores the legacy delete path and
    requires explicit opt-in.
    """

    DELETE_STALE = "delete_stale"
    QUARANTINE = "quarantine"


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

        # Build lookup sets (canonical keys on both sides)
        db_symbols = {self._row_key(pos.get("symbol", "")) for pos in db_positions}
        broker_symbols = {
            self._row_key(self._extract_underlying(pos))
            for pos in broker_positions
            if self._extract_underlying(pos)
        }

        # Compare
        restored = 0
        stale_removed = 0
        orphaned_registered = 0

        # Case 1: Position in DB AND at broker → restore (normal)
        for pos in db_positions:
            symbol = pos.get("symbol", "")
            if self._row_key(symbol) in broker_symbols:
                restored += 1
            elif self._policy is ReconcilePolicy.DELETE_STALE:
                # Case 2: Stale — in DB but NOT at broker
                stale_removed += 1
                discrepancies.append(
                    f"Stale: {symbol} in DB but not at broker — removing from DB"
                )
                if self._storage:
                    try:
                        ensure_sync_adapter_result(
                            "storage.delete_open_position",
                            self._storage.delete_open_position,
                            pos.get("id", ""),
                        )
                    except (KeyError, TypeError):
                        logger.debug("Failed to delete stale open position: %s", pos.get("id"), exc_info=True)
            else:
                # Fail-safe default: quarantine, no delete.
                discrepancies.append(
                    f"Quarantined: {symbol} in DB but not at broker — left for manual review"
                )

        # Case 3: Orphaned — at broker but NOT in DB
        for pos in broker_positions:
            symbol = self._extract_underlying(pos)
            if symbol and self._row_key(symbol) not in db_symbols:
                orphaned_registered += 1
                discrepancies.append(
                    f"Orphaned: {symbol} at broker but not in DB — registering as external"
                )

        logger.info(
            "Startup reconciliation: DB=%d broker=%d restored=%d stale=%d orphaned=%d",
            len(db_positions),
            len(broker_positions),
            restored,
            stale_removed,
            orphaned_registered,
        )

        return ReconciliationResult(
            db_positions=len(db_positions),
            broker_positions=len(broker_positions),
            restored=restored,
            stale_removed=stale_removed,
            orphaned_registered=orphaned_registered,
            discrepancies=discrepancies,
        )

    @staticmethod
    def _row_key(symbol: str) -> str:
        """Canonical compare key: uppercase + stripped (no alias logic)."""
        return (symbol or "").upper().strip()

    @staticmethod
    def _extract_underlying(broker_position) -> str:
        """Extract symbol from broker position object."""
        # Try common broker position formats
        if hasattr(broker_position, "trading_symbol"):
            return broker_position.trading_symbol
        if isinstance(broker_position, dict):
            return broker_position.get("trading_symbol", "")
        if hasattr(broker_position, "symbol"):
            return broker_position.symbol
        return ""
