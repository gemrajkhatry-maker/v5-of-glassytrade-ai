"""Regression tests for EventStore import integrity.

Covers the import-side guarantees added alongside the checksum hardening:

- export() preserves sequence + checksum metadata per event
- import_() validates sequence metadata: contiguous integers starting at 1,
  rejecting gaps, duplicates, out-of-order and missing sequences
- import_() verifies the exported checksum chain and rejects tampered payloads
- import_() is atomic: a failed import never clears or partially replaces an
  existing store
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from quant.event_store import EventStore
from quant.events import BarClosed, PositionOpened
from quant.state_machine import Bar, PositionState


def _bar_store(n: int = 3) -> EventStore:
    store = EventStore()
    for i in range(n):
        store.append(
            BarClosed(symbol="NIFTY", time=f"t{i}", bar=Bar(close=100.0 + i))
        )
    return store


class TestExportPreservesMetadata:
    def test_export_includes_sequence_and_checksum(self):
        store = _bar_store(2)
        exported = store.export()
        assert [d["sequence"] for d in exported] == [1, 2]
        assert all(d["checksum"] for d in exported)
        # The exported checksum is the stored chain checksum, not a placeholder.
        assert exported[0]["checksum"] == store._checksums[0]

    def test_roundtrip_preserves_order_and_chain(self):
        store = _bar_store(3)
        exported = store.export()
        store2 = EventStore()
        store2.import_(exported)
        assert [type(e).__name__ for e in store2.get_all()] == [
            "BarClosed",
            "BarClosed",
            "BarClosed",
        ]
        assert [e.bar.close for e in store2.get_all()] == [100.0, 101.0, 102.0]
        # The imported store's chain must verify (recomputed from reconstruction).
        assert store2.verify_chain() is True


class TestSequenceValidation:
    def test_gap_is_rejected(self):
        store = EventStore()
        with pytest.raises(ValueError, match="sequence"):
            store.import_(
                [
                    {"sequence": 1, "symbol": "NIFTY", "time": "t0",
                     "event_type": "BarClosed", "payload": {}},
                    {"sequence": 3, "symbol": "NIFTY", "time": "t1",
                     "event_type": "BarClosed", "payload": {}},
                ]
            )

    def test_duplicate_sequence_is_rejected(self):
        store = EventStore()
        with pytest.raises(ValueError, match="sequence"):
            store.import_(
                [
                    {"sequence": 1, "symbol": "NIFTY", "time": "t0",
                     "event_type": "BarClosed", "payload": {}},
                    {"sequence": 1, "symbol": "NIFTY", "time": "t1",
                     "event_type": "BarClosed", "payload": {}},
                ]
            )

    def test_out_of_order_is_rejected(self):
        store = EventStore()
        with pytest.raises(ValueError, match="sequence"):
            store.import_(
                [
                    {"sequence": 2, "symbol": "NIFTY", "time": "t1",
                     "event_type": "BarClosed", "payload": {}},
                    {"sequence": 1, "symbol": "NIFTY", "time": "t0",
                     "event_type": "BarClosed", "payload": {}},
                ]
            )

    def test_missing_sequence_is_rejected(self):
        store = EventStore()
        with pytest.raises(ValueError, match="sequence"):
            store.import_(
                [
                    {"symbol": "NIFTY", "time": "t0",
                     "event_type": "BarClosed", "payload": {}},
                ]
            )

    def test_sequence_must_start_at_one(self):
        store = EventStore()
        with pytest.raises(ValueError, match="sequence"):
            store.import_(
                [
                    {"sequence": 0, "symbol": "NIFTY", "time": "t0",
                     "event_type": "BarClosed", "payload": {}},
                ]
            )


class TestChecksumVerification:
    def test_tampered_payload_is_rejected(self):
        store = _bar_store(1)
        exported = store.export()
        # Tamper with the exported payload (flip the symbol).
        exported[0]["payload"]["symbol"] = "TAMPERED"
        store2 = EventStore()
        with pytest.raises(ValueError, match="checksum"):
            store2.import_(exported)

    def test_mixed_signed_unsigned_is_rejected(self):
        store = _bar_store(1)
        exported = store.export()
        exported.append(
            {"sequence": 2, "symbol": "NIFTY", "time": "t1",
             "event_type": "BarClosed", "payload": {}}
        )
        store2 = EventStore()
        with pytest.raises(ValueError, match="checksum"):
            store2.import_(exported)


class TestAtomicity:
    def test_failed_import_keeps_existing_store(self):
        store = _bar_store(2)
        before = [e.bar.close for e in store.get_all()]
        # Gap + forged sequence → validation must fail before any mutation.
        with pytest.raises(ValueError):
            store.import_(
                [
                    {"sequence": 1, "symbol": "NIFTY", "time": "t0",
                     "event_type": "BarClosed", "payload": {}},
                    {"sequence": 5, "symbol": "NIFTY", "time": "t1",
                     "event_type": "BarClosed", "payload": {}},
                ]
            )
        assert [e.bar.close for e in store.get_all()] == before
        assert store.verify_chain() is True

    def test_failed_import_due_to_checksum_keeps_existing_store(self):
        store = _bar_store(1)
        store.append(PositionOpened(
            symbol="NIFTY", time="t1",
            position=PositionState(id="abc", entry=100.0, size=10.0,
                                   sl=99.0, tp=102.0, side="LONG"),
        ))
        n_before = len(store)
        exported = store.export()
        exported[1]["payload"]["position"]["size"] = 999999.0  # tamper
        with pytest.raises(ValueError, match="checksum"):
            store.import_(exported)
        assert len(store) == n_before
        assert store.verify_chain() is True