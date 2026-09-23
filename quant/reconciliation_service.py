"""Single reconciliation service — one stale/orphan/size-mismatch policy.

Lives in ``quant/`` (stdlib only, zero backend imports) so every call site
can share it without a layering violation: the engine watchdogs
(``runtime.QuantEngine``, ``multi_engine.QuantCoordinator``) cannot import
backend code, while ``backend/app/domain/ops/startup_reconciliation.py``
(thin delegate) imports this module freely.

Role map (DB vs journal vs broker):
- DB-vs-broker (crash recovery): owned by backend ``StartupReconciliation``,
  which loads DB rows + broker rows, calls :func:`reconcile_sets`, and
  performs deletes ONLY under explicit ``DELETE_STALE`` opt-in.
- Restart rebuild (positions): owned by the coordinator loading SQLite
  open-position rows into ``QuantEngine.restore_position`` (baseline
  ``PositionOpened`` seed), then ``QuantEngine.startup_reconcile`` folds
  that seeded EventStore (execution book wins if the fold is empty). A fold,
  not a compare; no broker role. The JSONL journal is write-only durability
  audit — never replayed into the store on restart.
- Broker-vs-engine book (intraday drift): owned by
  ``QuantCoordinator._intraday_reconcile`` — detect-and-alert only; shares
  :func:`canonical_key`/:func:`partition_keys` from this module.
- State-vs-event-store (cached-state desync): owned by
  ``QuantEngine.periodic_reconcile`` — detect-only plus a RiskUpdated
  correction event; stays local.

Fail-safe default is QUARANTINE everywhere: this module never deletes,
closes, or adopts anything. Under ``DELETE_STALE`` it merely reports
``stale_keys``; the caller decides whether to act.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class ReconcilePolicy(enum.Enum):
    """Stale-row policy for DB-but-not-broker positions.

    Fail-safe default is QUARANTINE: stale rows are left in place for
    manual review. DELETE_STALE restores the legacy delete path and
    requires explicit opt-in.
    """

    DELETE_STALE = "delete_stale"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class PeriodicReconciliationResult:
    """Result of periodic state-vs-event-store reconciliation."""

    has_drift: bool
    risk_event_emitted: bool = False
    discrepancies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconcileOutcome:
    """Outcome of a DB/broker/journal set reconciliation.

    Counts only — the service performs no IO. ``stale_keys`` names the
    canonical keys the caller may delete, and only under
    ``ReconcilePolicy.DELETE_STALE`` (empty under QUARANTINE).
    """

    restored: int = 0
    quarantined: int = 0
    stale_removed: int = 0
    orphaned: int = 0
    journal_only: int = 0
    size_mismatches: int = 0
    stale_keys: tuple[str, ...] = ()
    discrepancies: tuple[str, ...] = ()


def canonical_key(symbol: str) -> str:
    """Canonical compare key: uppercase + stripped (no alias logic)."""
    return (symbol or "").upper().strip()


def canonical_contract_key(position: Any) -> str:
    """Return a stable execution identity, falling back to legacy symbol rows.

    Persisted rows store contract metadata under ``extra`` while broker rows
    expose the same fields at the top level. A metadata-bearing row must not
    match another expiry/strike/exchange merely because its display symbol is
    equal.
    """
    if isinstance(position, Mapping):
        metadata = position.get("extra") or position.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        merged = {**metadata, **position}
        fields = ("exchange", "expiry", "strike", "option_type", "lot_size", "tick_size", "multiplier")
        values = [merged.get(field) for field in fields]
        if any(value not in (None, "") for value in values):
            return "|".join([canonical_key(extract_symbol(position))] + [str(value or "").upper().strip() for value in values])
    return canonical_key(extract_symbol(position))


def extract_symbol(position: Any) -> str:
    """Extract a symbol from common DB/broker row shapes."""
    if hasattr(position, "trading_symbol"):
        return position.trading_symbol  # type: ignore[no-any-return]
    if isinstance(position, Mapping):
        symbol = position.get("trading_symbol", "") or position.get("symbol", "")
        return str(symbol)
    if hasattr(position, "symbol"):
        return str(position.symbol)
    return ""


def index_rows(
    rows: Any,
    *,
    symbol_of: Callable[[Any], str] = canonical_contract_key,
    size_of: Callable[[Any], float | None] | None = None,
) -> dict[str, float | None]:
    """Index raw rows by canonical key.

    Sizes are optional (``None`` = presence-only; skips size comparison),
    because the DB startup path tracks presence while the engine book
    tracks signed quantities.
    """
    indexed: dict[str, float | None] = {}
    for row in rows or []:
        key = canonical_key(symbol_of(row))
        if not key:
            continue
        indexed[key] = size_of(row) if size_of is not None else None
    return indexed


def partition_keys(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Split two key sets into (left-only, both, right-only)."""
    left_keys = frozenset(left)
    right_keys = frozenset(right)
    return (
        left_keys - right_keys,
        left_keys & right_keys,
        right_keys - left_keys,
    )


def _sizes_agree(sizes: list[float | None]) -> bool:
    known = [s for s in sizes if s is not None]
    if len(known) < 2:
        return True
    first = known[0]
    return all(abs(s - first) <= 1e-9 for s in known[1:])


def reconcile_sets(
    db: Mapping[str, float | None],
    broker: Mapping[str, float | None],
    journal: Mapping[str, float | None] | None = None,
    *,
    policy: ReconcilePolicy = ReconcilePolicy.QUARANTINE,
) -> ReconcileOutcome:
    """Reconcile DB/broker/journal presence (+ sizes when known).

    One outcome per key: restored / quarantined(+stale under opt-in) /
    orphaned / journal-only / size-mismatch. QUARANTINE (default) never
    reports ``stale_keys``.
    """
    journal = journal or {}
    db_keys = frozenset(db)
    broker_keys = frozenset(broker)
    journal_keys = frozenset(journal)

    restored = 0
    quarantined = 0
    stale_removed = 0
    orphaned = 0
    journal_only = 0
    size_mismatches = 0
    stale_keys: list[str] = []
    discrepancies: list[str] = []

    for key in sorted(db_keys | broker_keys | journal_keys):
        in_db = key in db_keys
        in_broker = key in broker_keys

        if in_db and in_broker:
            if _sizes_agree([db[key], broker[key], journal.get(key)]):
                restored += 1
            else:
                size_mismatches += 1
                discrepancies.append(
                    f"Size mismatch: {key} db={db[key]} "
                    f"vs broker={broker[key]} — broker qty stands, manual review needed"
                )
        elif in_db:
            # Stale — in DB but NOT at broker (journal either way).
            if policy is ReconcilePolicy.DELETE_STALE:
                stale_removed += 1
                stale_keys.append(key)
                discrepancies.append(
                    f"Stale: {key} in DB but not at broker — removing from DB"
                )
            else:
                quarantined += 1
                discrepancies.append(
                    f"Quarantined: {key} in DB but not at broker — left for manual review"
                )
        elif in_broker:
            orphaned += 1
            discrepancies.append(
                f"Orphaned: {key} at broker but not in DB — registering as external"
            )
        else:
            journal_only += 1
            discrepancies.append(
                f"Journal-only: {key} in journal but not in DB or broker — "
                "left for manual review"
            )

    return ReconcileOutcome(
        restored=restored,
        quarantined=quarantined,
        stale_removed=stale_removed,
        orphaned=orphaned,
        journal_only=journal_only,
        size_mismatches=size_mismatches,
        stale_keys=tuple(stale_keys),
        discrepancies=tuple(discrepancies),
    )
