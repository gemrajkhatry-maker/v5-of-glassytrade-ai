"""Tests for stale paper-position quarantine (Phase 0.2).

The current _spawn_engine loads ALL open positions from storage and restores
any row whose symbol matches the spawned engine — including positions for
contracts that are no longer in the active universe. On the running app, this
restored two stale positions (NIFTY 1 SEP 24050 CALL, MIDCPNIFTY 29 SEP 14700
PUT) that the scanner never selected. These unmanaged positions sit in the
engine's book but receive no quotes, no AMT, no exits.

Phase 0.2 introduces:
- PaperPositionReconciler classifies persisted positions against the active
  universe: OPEN, QUARANTINED_STALE_CONTRACT, QUARANTINED_UNRESOLVED.
- Only OPEN positions are restored; quarantined positions are preserved in
  storage but not loaded into any engine.
- Coordinator exposes quarantine status for readiness and telemetry.
"""
import json
import pytest

from quant.execution.paper_reconciliation import (
    PaperPositionReconciler,
    PaperPositionStatus,
    reconcile_paper_positions,
)


class FakeStorage:
    """Minimal storage double for position loading."""

    def __init__(self, rows=None):
        self._rows = rows or []

    def load_open_positions(self):
        return list(self._rows)


def _position_row(symbol, qty=1, open_price=100.0, **extra):
    """Build a row matching the shape load_open_positions returns."""
    row = {
        "symbol": symbol,
        "quantity": qty,
        "open_price": open_price,
        "side": "BUY",
        "open_time": "2026-09-07T09:15:00+05:30",
    }
    row.update(extra)
    return row


def test_paper_position_status_enum_exists():
    """PaperPositionStatus must define the canonical reconciliation outcomes."""
    assert PaperPositionStatus.OPEN.value == "OPEN"
    assert PaperPositionStatus.QUARANTINED_STALE_CONTRACT.value == "QUARANTINED_STALE_CONTRACT"
    assert PaperPositionStatus.QUARANTINED_UNRESOLVED.value == "QUARANTINED_UNRESOLVED"


def test_reconcile_returns_all_open_when_all_active():
    """Every persisted position belongs to the active universe — all restored."""
    storage = FakeStorage([
        _position_row("NIFTY 1 SEP 24200 CALL"),
        _position_row("BANKNIFTY 30 SEP 51000 PUT"),
    ])
    active = {"NIFTY 1 SEP 24200 CALL", "BANKNIFTY 30 SEP 51000 PUT"}
    result = reconcile_paper_positions(storage, active_universe=active)
    assert len(result.open_positions) == 2
    assert len(result.quarantined) == 0


def test_reconcile_quarantines_stale_contract():
    """A persisted position whose contract is not in the active universe
    must be quarantined, not restored."""
    storage = FakeStorage([
        _position_row("NIFTY 1 SEP 24200 CALL"),
        _position_row("NIFTY 1 SEP 24050 CALL"),  # stale: not in universe
    ])
    active = {"NIFTY 1 SEP 24200 CALL"}
    result = reconcile_paper_positions(storage, active_universe=active)
    assert len(result.open_positions) == 1
    assert result.open_positions[0]["symbol"] == "NIFTY 1 SEP 24200 CALL"
    assert len(result.quarantined) == 1
    assert result.quarantined[0].status == PaperPositionStatus.QUARANTINED_STALE_CONTRACT
    assert result.quarantined[0].symbol == "NIFTY 1 SEP 24050 CALL"


def test_reconcile_quarantines_unresolved_identity():
    """A persisted position with an unparseable symbol must be quarantined
    separately from stale contracts — it could be a data error."""
    storage = FakeStorage([
        _position_row("NIFTY 1 SEP 24200 CALL"),
        _position_row(""),  # empty symbol
    ])
    active = {"NIFTY 1 SEP 24200 CALL"}
    result = reconcile_paper_positions(storage, active_universe=active)
    assert len(result.quarantined) == 1
    assert result.quarantined[0].status == PaperPositionStatus.QUARANTINED_UNRESOLVED


def test_reconcile_with_empty_storage_is_noop():
    """No persisted positions — nothing to reconcile."""
    storage = FakeStorage([])
    active = {"NIFTY 1 SEP 24200 CALL"}
    result = reconcile_paper_positions(storage, active_universe=active)
    assert len(result.open_positions) == 0
    assert len(result.quarantined) == 0


def test_reconcile_with_no_active_universe_quarantines_all():
    """If the scanner produced no active contracts (weekend, holiday, empty scan),
    all persisted positions are stale — none should be restored."""
    storage = FakeStorage([
        _position_row("NIFTY 1 SEP 24200 CALL"),
        _position_row("BANKNIFTY 30 SEP 51000 PUT"),
    ])
    result = reconcile_paper_positions(storage, active_universe=set())
    assert len(result.open_positions) == 0
    assert len(result.quarantined) == 2
    assert all(
        q.status == PaperPositionStatus.QUARANTINED_STALE_CONTRACT
        for q in result.quarantined
    )


def test_reconcile_does_not_delete_quarantined_rows():
    """Quarantine preserves the row in storage — only the in-memory restore is
    skipped. Automatic deletion would destroy the audit trail."""
    rows = [
        _position_row("NIFTY 1 SEP 24200 CALL"),
        _position_row("NIFTY 1 SEP 24050 CALL"),
    ]
    storage = FakeStorage(rows)
    active = {"NIFTY 1 SEP 24200 CALL"}
    reconcile_paper_positions(storage, active_universe=active)
    # Storage rows must be untouched
    assert len(storage._rows) == 2


def test_reconcile_preserves_all_row_fields_for_quarantined():
    """Quarantined entries must carry the full original row for audit display."""
    storage = FakeStorage([
        _position_row("NIFTY 1 SEP 24050 CALL", qty=5, open_price=250.5, side="SELL"),
    ])
    active = set()
    result = reconcile_paper_positions(storage, active_universe=active)
    assert len(result.quarantined) == 1
    q = result.quarantined[0]
    assert q.row["symbol"] == "NIFTY 1 SEP 24050 CALL"
    assert q.row["quantity"] == 5
    assert q.row["open_price"] == 250.5


def test_reconcile_result_exposes_summary():
    """ReconciliationResult must provide a compact summary for readiness/telemetry."""
    storage = FakeStorage([
        _position_row("NIFTY 1 SEP 24200 CALL"),
        _position_row("NIFTY 1 SEP 24050 CALL"),
        _position_row(""),
    ])
    active = {"NIFTY 1 SEP 24200 CALL"}
    result = reconcile_paper_positions(storage, active_universe=active)
    summary = result.summary()
    assert summary["open"] == 1
    assert summary["quarantined_stale"] == 1
    assert summary["quarantined_unresolved"] == 1
    assert summary["total_persisted"] == 3


def test_reconciler_class_is_instantiable():
    """PaperPositionReconciler can be constructed with storage and universe."""
    storage = FakeStorage([])
    reconciler = PaperPositionReconciler(storage, active_universe={"NIFTY 1 SEP 24200 CALL"})
    result = reconciler.reconcile()
    assert len(result.open_positions) == 0
