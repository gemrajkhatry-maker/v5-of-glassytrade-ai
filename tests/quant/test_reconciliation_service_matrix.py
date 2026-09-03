# tests/quant/test_reconciliation_service_matrix.py
"""Matrix test for the single reconciliation service (Plan E Task 4, Half A).

DB-only / broker-only / journal-only / size-mismatch → one outcome each.
QUARANTINE default: no deletes anywhere (the service never deletes; under
DELETE_STALE it only *reports* stale keys for the caller to remove).
"""
from quant.reconciliation_service import (
    ReconcilePolicy,
    index_rows,
    reconcile_sets,
)


def _rows(*symbols):
    return index_rows([{"symbol": s} for s in symbols])


def test_matrix_db_only_quarantined_no_deletes():
    outcome = reconcile_sets(
        _rows("NIFTY AUG FUT"), {}, {},
        policy=ReconcilePolicy.QUARANTINE,
    )
    assert outcome.quarantined == 1
    assert outcome.stale_removed == 0
    assert outcome.stale_keys == ()
    assert outcome.restored == 0
    assert outcome.orphaned == 0
    assert any("quarantin" in d.lower() for d in outcome.discrepancies)


def test_matrix_broker_only_orphaned():
    outcome = reconcile_sets(
        {}, _rows("BANKNIFTY AUG FUT"), {},
        policy=ReconcilePolicy.QUARANTINE,
    )
    assert outcome.orphaned == 1
    assert outcome.restored == 0
    assert outcome.quarantined == 0
    assert outcome.stale_removed == 0
    assert any("orphan" in d.lower() for d in outcome.discrepancies)


def test_matrix_journal_only_flagged_no_deletes():
    outcome = reconcile_sets(
        {}, {}, _rows("NIFTY AUG FUT"),
        policy=ReconcilePolicy.QUARANTINE,
    )
    assert outcome.journal_only == 1
    assert outcome.restored == 0
    assert outcome.quarantined == 0
    assert outcome.orphaned == 0
    assert outcome.stale_removed == 0
    assert outcome.stale_keys == ()
    assert len(outcome.discrepancies) == 1


def test_matrix_size_mismatch_never_deletes():
    db = index_rows([{"symbol": "NIFTY AUG FUT", "size": 10.0}], size_of=lambda r: r["size"])
    broker = index_rows(
        [{"symbol": "NIFTY AUG FUT", "size": 15.0}], size_of=lambda r: r["size"]
    )
    for policy in (ReconcilePolicy.QUARANTINE, ReconcilePolicy.DELETE_STALE):
        outcome = reconcile_sets(db, broker, {}, policy=policy)
        assert outcome.size_mismatches == 1
        assert outcome.restored == 0
        assert outcome.stale_removed == 0
        assert outcome.stale_keys == ()


def test_matrix_match_restores():
    db = index_rows([{"symbol": "NIFTY AUG FUT", "size": 10.0}], size_of=lambda r: r["size"])
    broker = index_rows(
        [{"symbol": "nifty aug fut ", "size": 10.0}], size_of=lambda r: r["size"]
    )
    outcome = reconcile_sets(db, broker, {})
    assert outcome.restored == 1
    assert outcome.discrepancies == ()
