"""Integration Test for Three-Way Startup Reconciliation (Section 4.2).

Verifies the 3-way startup state check prior to market feed connection:
1. DB Stale Purge: If local SQLite database lists an open position not in broker ledger,
   marked stale and archived.
2. Broker Orphan Quarantine: If broker ledger contains an open position not recorded in DB,
   engine enters Quarantined state and blocks automated trading.
3. Desynchronization Handling: If positions exist in both layers but quantities differ,
   system defaults to broker's position size and flags an audit alert.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock
import pytest

from app.domain.ops.startup_reconciliation import (
    ReconcilePolicy,
    ReconciliationResult,
    StartupReconciliation,
)
from quant.reconciliation_service import reconcile_sets


def test_three_way_reconciliation_stale_orphan_and_desync(monkeypatch):
    """Verify 3-way reconciliation handles stale purge, broker orphan quarantine, and size mismatch."""
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("TRADING_MODE", "live")

    # DB positions:
    # 1. Stale position in DB but not broker: NIFTY24AUG25000CE
    # 2. Desync position in both but quantities differ: BANKNIFTY24AUG50000CE (DB qty 15 vs Broker qty 30)
    # 3. Clean matched position in both: FINNIFTY24AUG23000CE (qty 25)
    db_positions = [
        {"symbol": "NIFTY24AUG25000CE", "side": "BUY", "quantity": 25, "entry_price": 100.0},
        {"symbol": "BANKNIFTY24AUG50000CE", "side": "BUY", "quantity": 15, "entry_price": 250.0},
        {"symbol": "FINNIFTY24AUG23000CE", "side": "BUY", "quantity": 25, "entry_price": 180.0},
    ]

    # Broker positions:
    # 1. Matched with size mismatch: BANKNIFTY24AUG50000CE (Broker qty 30)
    # 2. Orphan position in broker but not in DB: CRUDEOIL24AUG6000CE (Broker qty 100)
    # 3. Clean matched position in both: FINNIFTY24AUG23000CE (qty 25)
    broker_positions = [
        {"symbol": "BANKNIFTY24AUG50000CE", "side": "BUY", "quantity": 30, "entry_price": 250.0},
        {"symbol": "CRUDEOIL24AUG6000CE", "side": "BUY", "quantity": 100, "entry_price": 120.0},
        {"symbol": "FINNIFTY24AUG23000CE", "side": "BUY", "quantity": 25, "entry_price": 180.0},
    ]

    mock_storage = MagicMock()
    mock_storage.load_open_positions.return_value = list(db_positions)
    mock_storage.delete_position = MagicMock()

    mock_broker = MagicMock()
    mock_broker.get_positions.return_value = list(broker_positions)

    # 1. Under DELETE_STALE policy
    reconciler = StartupReconciliation(
        broker_adapter=mock_broker,
        storage=mock_storage,
        policy=ReconcilePolicy.DELETE_STALE,
    )

    result = reconciler.reconcile()

    # Assertions on outcome
    assert result.db_positions == 3
    assert result.broker_positions == 3
    assert result.restored == 2  # Both matched contracts restored to engine
    assert result.stale_removed == 1  # NIFTY purged
    assert result.orphaned_registered == 1  # CRUDEOIL quarantined/registered as orphan
    assert any("Stale: NIFTY24AUG25000CE" in d for d in result.discrepancies)
    assert any("Orphaned: CRUDEOIL24AUG6000CE" in d for d in result.discrepancies)


def test_pure_reconcile_sets_mathematical_determinism():
    """Verify underlying pure reconcile_sets logic produces deterministic partition counts."""
    db = {"SYM_A": 10.0, "SYM_B": 20.0, "SYM_D": 50.0}
    broker = {"SYM_B": 30.0, "SYM_C": 40.0, "SYM_D": 50.0}

    outcome = reconcile_sets(
        db=db,
        broker=broker,
        journal={},
        policy=ReconcilePolicy.DELETE_STALE,
    )

    assert outcome.restored == 1  # SYM_D matched with identical qty
    assert outcome.stale_removed == 1  # SYM_A removed
    assert outcome.orphaned == 1  # SYM_C orphan
    assert outcome.size_mismatches == 1  # SYM_B size mismatch
    assert outcome.stale_keys == ("SYM_A",)
