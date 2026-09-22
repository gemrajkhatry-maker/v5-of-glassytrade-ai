"""TDD tests for EventStore hardening.

These tests define the contract for:
- SHA-256 checksum chain (tamper-evident)
- Dead-letter queue for failed handlers
- Full import_() reconstruction
- Per-bus event IDs
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class TestEventStoreHardening:
    """Production-grade EventStore features."""

    def test_checksum_chain(self):
        """Each event should have a checksum of previous + current."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        for i in range(5):
            store.append(
                BarClosed(symbol="NIFTY", time=f"t{i}", bar=Bar(close=100.0 + i))
            )
        assert store.verify_chain() is True

    def test_tamper_detection(self):
        """Tampering should break the checksum chain."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=Bar(close=100.0)))
        store._events[0] = BarClosed(symbol="TAMPERED", time="t0", bar=Bar(close=999.0))
        assert store.verify_chain() is False

    def test_import_reconstructs_events(self):
        """import_() should fully reconstruct Event objects."""
        from quant.event_store import EventStore
        from quant.events import PositionOpened
        from quant.state_machine import PositionState

        store1 = EventStore()
        pos = PositionState(id="abc", entry=100, size=100, sl=95, tp=110, side="LONG")
        store1.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        exported = store1.export()

        store2 = EventStore()
        store2.import_(exported)
        assert len(store2.get_all()) == 1
        imported_event = store2.get_all()[0]
        assert isinstance(imported_event, PositionOpened)
        assert imported_event.position.id == "abc"

    def test_event_id_is_per_bus(self):
        """Each EventBus should have independent event IDs."""
        from quant.events import EventBus

        bus1 = EventBus()
        bus2 = EventBus()
        id1 = bus1.next_event_id()
        id2 = bus2.next_event_id()
        assert id1 == "1"
        assert id2 == "1"
