"""TDD tests for full migration of QuantEngine to EngineState + EventStore.

These tests define the contract for the migration:
- EventStore is the SOLE source of truth
- EngineState is derived from events via apply_event()
- No scattered state (_position, _pyramid_positions, etc.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from quant.brokers.gateway import Tick
from quant.event_store import EventStore
from quant.events import BarClosed, PositionClosed, PositionOpened
from quant.execution.order import Order, Position
from quant.decision.signal_builder import Signal
from quant.decision.decision_service import QuantDecision
from quant.runtime import QuantEngine
from quant.state_machine import EngineState, PositionState


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


class _FixedDecisionService:
    """Returns a canned approved decision for testing."""

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    def evaluate(self, ctx):
        return QuantDecision(True, self._signal, "Triple-A", "AGGRESSION", ())


class _FixedStrategy:
    """Strategy that delegates to a fixed decision service."""

    def __init__(self, signal: Signal) -> None:
        self._service = _FixedDecisionService(signal)

    def on_bar(self, bar, auction, amt_dto):
        pass

    def should_enter(self, ctx):
        return self._service.evaluate(ctx)


def _healthy_stop_signal() -> Signal:
    # 20% stop -> 1M (SessionRisk default) * 1% / 20.0 = 500 units, under the ceiling.
    return Signal(type="LONG", reason="test", entry=100.0, sl=80.0, tp=140.0,
                  rr=2.0, model_label="Triple-A", symbol="NIFTY", timestamp="t")


def _ticks_with_entry():
    """Ticks that produce a position entry."""
    # Quiet range bars to build up history, then a signal
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 450, 50))
    out.append(Tick("t301", 100.0, 10, 6, 4))
    out.append(Tick("t302", 100.4, 20, 14, 6))
    out.append(Tick("t303", 100.6, 20, 14, 6))
    for i, price in enumerate([100.8, 101.0, 101.2, 101.4]):
        out.append(Tick(f"t{304 + i}", price, 10, 6, 4))
    return out


# ---------------------------------------------------------------------------
# EngineMigration tests
# ---------------------------------------------------------------------------

class TestEngineMigration:
    def test_run_inner_uses_event_store(self):
        """_run_inner should append events to EventStore."""
        ticks = _make_ticks()
        engine = create_engine_with_ticks(ticks)
        engine.run()
        events = engine.event_store.get_all()
        assert len(events) > 0
        assert any(isinstance(e, BarClosed) for e in events)

    def test_state_derives_from_events(self):
        """Engine state should match event store fold."""
        ticks = _make_ticks()
        engine = create_engine_with_ticks(ticks)
        engine.run()
        derived_state = engine.event_store.fold()
        assert engine.state == derived_state

    def test_no_scattered_state(self):
        """Engine should NOT have _position, _pyramid_positions."""
        ticks = _make_ticks()
        engine = create_engine_with_ticks(ticks)
        assert not hasattr(engine, '_position')
        assert not hasattr(engine, '_pyramid_positions')

    def test_decide_updates_state(self):
        """_decide should update state via events."""
        ticks = _make_ticks()
        engine = create_engine_with_ticks(ticks)
        engine.run()
        assert engine.state.sequence > 0

    def test_manage_exit_updates_state(self):
        """_manage_exit should update state via events."""
        import quant.position_manager as pm
        # Force session close so the position gets closed
        original_sfe = pm.session_force_exit
        pm.session_force_exit = lambda t, market="NSE", contract_expiry=None: True
        try:
            ticks = _ticks_with_entry()
            engine = create_engine_with_ticks(ticks)
            engine._strategy = _FixedStrategy(_healthy_stop_signal())
            engine.run()
            # After running, state should reflect the exit (position closed)
            # The position should be None after session close or exit
            assert engine.state.position is None
        finally:
            pm.session_force_exit = original_sfe

    def test_double_close_prevented(self):
        """Double-close should be impossible by construction."""
        # Create ticks that would trigger multiple close attempts
        ticks = _ticks_with_entry()
        engine = create_engine_with_ticks(ticks)
        engine._strategy = _FixedStrategy(_healthy_stop_signal())
        engine.run()
        closed_events = [e for e in engine.event_store.get_all() if isinstance(e, PositionClosed)]
        position_ids = [e.fill.position._id for e in closed_events]
        assert len(position_ids) == len(set(position_ids))
