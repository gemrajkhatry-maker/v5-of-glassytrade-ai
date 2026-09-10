"""TDD tests for Phase 1: Centralized EngineState.

These tests define the contract BEFORE implementation.
All tests should FAIL initially (RED phase).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

class MockBar:
    def __init__(self, close=100.0):
        self.time = "t0"
        self.open = 100.0
        self.high = 101.0
        self.low = 99.0
        self.close = close
        self.volume = 100.0
        self.vwap = 100.0
        self.buy_volume = 50.0
        self.sell_volume = 50.0
        self.oi = 1000.0


class MockSignal:
    def __init__(self):
        self.type = "LONG"
        self.reason = "test"
        self.entry = 100.0
        self.sl = 95.0
        self.tp = 110.0
        self.rr = 2.0
        self.model_label = "Triple-A"
        self.symbol = "NIFTY"
        self.timestamp = "t0"


class MockOrder:
    def __init__(self):
        self.signal = MockSignal()
        self.quantity = 100.0


class MockPosition:
    def __init__(self, pos_id="abc-123"):
        self._id = pos_id
        self.order = MockOrder()
        self.open_price = 100.0
        self.open_time = "t0"
        self.size = 100.0
        self.realized_pnl = 0.0
        self.pyramid_level = 0
        self.is_pyramid = False


# ---------------------------------------------------------------------------
# EngineState tests
# ---------------------------------------------------------------------------

class TestEngineState:
    """EngineState is a frozen dataclass with immutable transitions."""

    def test_initial_state(self):
        """Initial state has no position, no bar, default risk."""
        from quant.state_machine import EngineState
        
        state = EngineState(symbol="NIFTY")
        
        assert state.symbol == "NIFTY"
        assert state.position is None
        assert state.last_bar is None
        assert state.pyramids == ()
        assert state.sequence == 0

    def test_state_is_immutable(self):
        """Frozen dataclass cannot be mutated."""
        from quant.state_machine import EngineState
        
        state = EngineState(symbol="NIFTY")
        
        with pytest.raises(AttributeError):
            state.symbol = "BANKNIFTY"

    def test_with_bar_returns_new_state(self):
        """with_bar returns a new state; original is unchanged."""
        from quant.state_machine import EngineState
        
        state = EngineState(symbol="NIFTY")
        bar = MockBar()
        
        new_state = state.with_bar(bar)
        
        assert state.last_bar is None  # Original unchanged
        assert new_state.last_bar is bar  # New state has bar
        assert new_state.sequence == state.sequence + 1

    def test_with_position_returns_new_state(self):
        """with_position returns a new state with position set."""
        from quant.state_machine import EngineState, PositionState
        
        state = EngineState(symbol="NIFTY")
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        
        new_state = state.with_position(pos)
        
        assert state.position is None  # Original unchanged
        assert new_state.position == pos  # New state has position
        assert new_state.sequence == state.sequence + 1

    def test_without_position_returns_new_state(self):
        """without_position returns a new state with position cleared."""
        from quant.state_machine import EngineState, PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos)
        
        new_state = state.without_position()
        
        assert state.position == pos  # Original unchanged
        assert new_state.position is None  # New state has no position
        assert new_state.pyramids == ()  # Pyramids cleared too

    def test_with_risk_returns_new_state(self):
        """with_risk returns a new state with updated risk."""
        from quant.state_machine import EngineState, RiskState
        
        state = EngineState(symbol="NIFTY")
        risk = RiskState(daily_pnl=-500.0, trades_today=2, halted=False)
        
        new_state = state.with_risk(risk)
        
        assert state.risk.daily_pnl == 0.0  # Original unchanged
        assert new_state.risk.daily_pnl == -500.0  # New state has risk

    def test_sequence_increments_on_each_transition(self):
        """Sequence number increments on each state transition."""
        from quant.state_machine import EngineState
        
        state = EngineState(symbol="NIFTY")
        assert state.sequence == 0
        
        s1 = state.with_bar(MockBar())
        assert s1.sequence == 1
        
        s2 = s1.with_bar(MockBar(close=101.0))
        assert s2.sequence == 2
        
        s3 = s2.with_risk(MockRiskState())
        assert s3.sequence == 3


# ---------------------------------------------------------------------------
# PositionState tests
# ---------------------------------------------------------------------------

class TestPositionState:
    """PositionState is a frozen dataclass representing a position."""

    def test_position_state_creation(self):
        """PositionState can be created with all fields."""
        from quant.state_machine import PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
            pyramid_level=0,
            is_pyramid=False,
        )
        
        assert pos.id == "abc-123"
        assert pos.entry == 100.0
        assert pos.size == 100.0
        assert pos.sl == 95.0
        assert pos.tp == 110.0
        assert pos.side == "LONG"

    def test_position_state_is_immutable(self):
        """PositionState is frozen."""
        from quant.state_machine import PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        
        with pytest.raises(AttributeError):
            pos.entry = 200.0

    def test_position_state_equality(self):
        """Two PositionStates with same fields are equal."""
        from quant.state_machine import PositionState
        
        pos1 = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        pos2 = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        
        assert pos1 == pos2


# ---------------------------------------------------------------------------
# RiskState tests
# ---------------------------------------------------------------------------

class TestRiskState:
    """RiskState is a frozen dataclass representing risk status."""

    def test_risk_state_initial(self):
        """Initial risk state has zero P&L and no halt."""
        from quant.state_machine import RiskState
        
        risk = RiskState()
        
        assert risk.daily_pnl == 0.0
        assert risk.trades_today == 0
        assert risk.halted is False
        assert risk.halt_reason == ""

    def test_risk_state_can_be_halted(self):
        """Risk state can be halted with a reason."""
        from quant.state_machine import RiskState
        
        risk = RiskState(halted=True, halt_reason="daily loss limit")
        
        assert risk.halted is True
        assert risk.halt_reason == "daily loss limit"

    def test_risk_state_is_immutable(self):
        """RiskState is frozen."""
        from quant.state_machine import RiskState
        
        risk = RiskState()
        
        with pytest.raises(AttributeError):
            risk.daily_pnl = -500.0


# ---------------------------------------------------------------------------
# MockRiskState for tests that need it
# ---------------------------------------------------------------------------

class MockRiskState:
    def __init__(self):
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""


# ---------------------------------------------------------------------------
# Integration test: state transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    """Test that state transitions compose correctly."""

    def test_full_entry_exit_cycle(self):
        """Entry → exit cycle produces correct final state."""
        from quant.state_machine import EngineState, PositionState
        
        # Start with empty state
        state = EngineState(symbol="NIFTY")
        assert state.position is None
        
        # Entry
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = state.with_position(pos)
        assert state.position == pos
        
        # Exit
        state = state.without_position()
        assert state.position is None

    def test_bar_updates_dont_affect_position(self):
        """Bar updates preserve position state."""
        from quant.state_machine import EngineState, PositionState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos)
        
        # Update bar
        new_state = state.with_bar(MockBar(close=105.0))
        
        assert new_state.position == pos  # Position preserved
        assert new_state.last_bar.close == 105.0  # Bar updated

    def test_risk_updates_dont_affect_position(self):
        """Risk updates preserve position state."""
        from quant.state_machine import EngineState, PositionState, RiskState
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos)
        
        # Update risk
        risk = RiskState(daily_pnl=-500.0, trades_today=1)
        new_state = state.with_risk(risk)
        
        assert new_state.position == pos  # Position preserved
        assert new_state.risk.daily_pnl == -500.0  # Risk updated


def test_stop_moved_folds_into_the_projected_stop():
    """D-7: StopMoved was journaled but never folded, so the UI showed the
    submitted stop while ExitEngine enforced the ratcheted one."""
    from quant.state_machine import EngineState, PositionState
    from quant.events import StopMoved
    from quant.transitions import apply_event

    state = EngineState(symbol="SYM")
    state = state.with_position(
        PositionState(id="p1", entry=100.0, size=10.0, sl=99.0, tp=103.0, side="LONG")
    )
    assert state.position.sl == 99.0

    state = apply_event(state, StopMoved(symbol="SYM", time="t1", old_sl=99.0,
                                         new_sl=100.5, reason="TRAIL_RATCHET"))
    assert state.position.sl == 100.5

    # Stale/replayed moves must not loosen an already-ratcheted stop.
    state = apply_event(state, StopMoved(symbol="SYM", time="t2", old_sl=100.5,
                                         new_sl=98.0, reason="TRAIL_RATCHET"))
    assert state.position.sl == 100.5


def test_stop_moved_folds_into_pyramids_and_only_tightens():
    """D-7(b): the fold also covers pyramid legs, is monotonic per leg, and a
    short's stop only tightens downward."""
    from quant.state_machine import EngineState, PositionState
    from quant.events import PositionOpened, StopMoved
    from quant.transitions import apply_event

    base = PositionState(id="p1", entry=100.0, size=10.0, sl=100.0, tp=103.0, side="LONG")
    pyr = PositionState(id="p2", entry=101.0, size=5.0, sl=98.0, tp=103.0,
                        side="LONG", is_pyramid=True, pyramid_level=1)
    state = EngineState(symbol="SYM").with_position(base)
    state = apply_event(state, PositionOpened(symbol="SYM", time="t0", position=pyr))

    # A move that does not tighten the base still tightens the loose pyramid.
    state = apply_event(state, StopMoved(symbol="SYM", time="t1", old_sl=98.0,
                                         new_sl=99.5, reason="PYRAMID_RATCHET"))
    assert state.position.sl == 100.0
    assert state.pyramids[0].sl == 99.5

    # Monotonic: a stale loosening move is ignored on the pyramid too.
    state = apply_event(state, StopMoved(symbol="SYM", time="t2", old_sl=99.5,
                                         new_sl=98.0, reason="TRAIL_RATCHET"))
    assert state.pyramids[0].sl == 99.5

    # SHORT: only a *lower* stop is a tightening move.
    short = PositionState(id="s1", entry=100.0, size=-10.0, sl=101.0, tp=97.0, side="SHORT")
    sstate = EngineState(symbol="SYM").with_position(short)
    sstate = apply_event(sstate, StopMoved(symbol="SYM", time="t3", old_sl=101.0,
                                           new_sl=102.0, reason="TRAIL_RATCHET"))
    assert sstate.position.sl == 101.0
    sstate = apply_event(sstate, StopMoved(symbol="SYM", time="t4", old_sl=101.0,
                                           new_sl=100.0, reason="TRAIL_RATCHET"))
    assert sstate.position.sl == 100.0


def test_stop_moved_does_not_resurrect_a_closed_position():
    """A stale StopMoved after the position closed must be a no-op, not an
    invented position."""
    from quant.state_machine import EngineState
    from quant.events import StopMoved
    from quant.transitions import apply_event

    state = apply_event(
        EngineState(symbol="SYM"),
        StopMoved(symbol="SYM", time="t1", old_sl=99.0, new_sl=100.5,
                  reason="TRAIL_RATCHET"),
    )
    assert state.position is None
    assert state == EngineState(symbol="SYM")
