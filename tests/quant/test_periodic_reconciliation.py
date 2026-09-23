"""TDD tests for periodic reconciliation between EngineState and EventStore.

These tests define the contract for periodic_reconcile() and startup reconciliation.
All tests should FAIL initially (RED phase).
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from quant.brokers.gateway import Tick
from quant.event_store import EventStore
from quant.events import PositionOpened
from quant.runtime import QuantEngine
from quant.state_machine import PositionState, RiskState


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

class SyntheticGateway:
    """Minimal gateway for feeding ticks deterministically."""

    def __init__(self, ticks):
        self._ticks = list(ticks)
        self._idx = 0

    def subscribe(self, symbol):
        pass

    def next_tick(self):
        if self._idx >= len(self._ticks):
            return None
        tick = self._ticks[self._idx]
        self._idx += 1
        return tick

    def try_next_tick(self):
        return self.next_tick()


def _make_ticks(n=20):
    """Generate n quiet ticks at price 100."""
    return [Tick(f"t{i}", 100.0, 10.0, 6.0, 4.0) for i in range(n)]


def create_engine_with_ticks(ticks):
    """Create a QuantEngine fed by synthetic ticks."""
    return QuantEngine(SyntheticGateway(ticks), "NIFTY", interval_seconds=1)


def create_engine_with_event_store(store):
    """Create a QuantEngine with a pre-populated event store."""
    engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=1)
    engine.event_store = store
    return engine


# ---------------------------------------------------------------------------
# Periodic reconciliation tests
# ---------------------------------------------------------------------------

class TestPeriodicReconciliation:
    def test_periodic_reconcile_detects_drift(self):
        """Periodic reconcile should detect state drift."""
        ticks = _make_ticks()
        engine = create_engine_with_ticks(ticks)
        engine.run()
        # Simulate: journal has a position but in-memory state lost it (drift)
        pos = PositionState(
            id="pos-001",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        engine.event_store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        result = engine.periodic_reconcile()
        assert result.has_drift is True

    def test_startup_reconcile(self):
        """Startup reconcile should rebuild from journal."""
        store = EventStore()
        pos = PositionState(
            id="pos-001",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        engine = create_engine_with_event_store(store)
        # Startup reconcile rebuilds state from event store
        engine.startup_reconcile()
        assert engine.state.position is not None

    def test_reconcile_emits_risk_event(self):
        """Reconcile should emit RiskUpdated on discrepancy."""
        ticks = _make_ticks()
        engine = create_engine_with_ticks(ticks)
        engine.run()
        # Simulate risk drift: halt risk in state
        engine.state = engine.state.with_risk(RiskState(halted=True))
        result = engine.periodic_reconcile()
        assert result.risk_event_emitted is True
