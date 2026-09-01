"""TDD tests for Phase 2: Atomic state transitions.

These tests define the contract for event-driven state transitions.
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
# Event tests
# ---------------------------------------------------------------------------

class TestEvents:
    """Events are frozen dataclasses."""

    def test_bar_closed_event(self):
        """BarClosed event carries bar data."""
        from quant.events import BarClosed
        
        bar = MockBar()
        event = BarClosed(symbol="NIFTY", time="t0", bar=bar)
        
        assert event.symbol == "NIFTY"
        assert event.bar is bar

    def test_position_opened_event(self):
        """PositionOpened event carries position data."""
        from quant.events import PositionOpened
        
        pos = MockPosition()
        event = PositionOpened(symbol="NIFTY", time="t0", position=pos)
        
        assert event.symbol == "NIFTY"
        assert event.position is pos

    def test_position_closed_event(self):
        """PositionClosed event carries fill data."""
        from quant.events import PositionClosed
        
        fill = MockFill()
        event = PositionClosed(symbol="NIFTY", time="t0", fill=fill)
        
        assert event.symbol == "NIFTY"
        assert event.fill is fill

    def test_risk_updated_event(self):
        """RiskUpdated event carries risk data."""
        from quant.events import RiskUpdated
        
        risk = MockRisk()
        event = RiskUpdated(symbol="NIFTY", time="t0", risk=risk)
        
        assert event.symbol == "NIFTY"
        assert event.risk is risk

    def test_event_is_frozen(self):
        """Events are immutable."""
        from quant.events import BarClosed
        
        bar = MockBar()
        event = BarClosed(symbol="NIFTY", time="t0", bar=bar)
        
        with pytest.raises(AttributeError):
            event.symbol = "BANKNIFTY"


# ---------------------------------------------------------------------------
# apply_event tests
# ---------------------------------------------------------------------------

class TestApplyEvent:
    """apply_event is a pure function: (State, Event) -> State."""

    def test_apply_bar_closed(self):
        """BarClosed event updates last_bar."""
        from quant.state_machine import EngineState, Bar
        from quant.events import BarClosed
        
        state = EngineState(symbol="NIFTY")
        bar = Bar(time="t0", close=100.0)
        event = BarClosed(symbol="NIFTY", time="t0", bar=bar)
        
        new_state = apply_event(state, event)
        
        assert new_state.last_bar is bar
        assert state.last_bar is None  # Original unchanged

    def test_apply_position_opened(self):
        """PositionOpened event sets position."""
        from quant.state_machine import EngineState, PositionState
        from quant.events import PositionOpened
        
        state = EngineState(symbol="NIFTY")
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        event = PositionOpened(symbol="NIFTY", time="t0", position=pos)
        
        new_state = apply_event(state, event)
        
        assert new_state.position == pos
        assert state.position is None  # Original unchanged

    def test_apply_position_closed(self):
        """PositionClosed event clears position."""
        from quant.state_machine import EngineState, PositionState
        from quant.events import PositionOpened, PositionClosed
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos)
        
        fill = MockFill()
        event = PositionClosed(symbol="NIFTY", time="t0", fill=fill)
        
        new_state = apply_event(state, event)
        
        assert new_state.position is None
        assert state.position == pos  # Original unchanged

    def test_apply_risk_updated(self):
        """RiskUpdated event updates risk."""
        from quant.state_machine import EngineState, RiskState
        from quant.events import RiskUpdated
        
        state = EngineState(symbol="NIFTY")
        risk = RiskState(daily_pnl=-500.0, trades_today=2, halted=True)
        event = RiskUpdated(symbol="NIFTY", time="t0", risk=risk)
        
        new_state = apply_event(state, event)
        
        assert new_state.risk == risk
        assert state.risk.daily_pnl == 0.0  # Original unchanged

    def test_apply_unknown_event_is_noop(self):
        """Unknown events don't change state."""
        from quant.state_machine import EngineState
        from quant.events import Event
        
        state = EngineState(symbol="NIFTY")
        event = Event(symbol="NIFTY", time="t0")
        
        new_state = apply_event(state, event)
        
        assert new_state == state

    def test_apply_event_is_pure(self):
        """apply_event doesn't mutate inputs."""
        from quant.state_machine import EngineState, Bar
        from quant.events import BarClosed
        
        state = EngineState(symbol="NIFTY")
        bar = Bar(time="t0", close=100.0)
        event = BarClosed(symbol="NIFTY", time="t0", bar=bar)
        
        # Call twice with same inputs
        new_state1 = apply_event(state, event)
        new_state2 = apply_event(state, event)
        
        # Same result
        assert new_state1 == new_state2
        # Original state unchanged
        assert state.last_bar is None


# ---------------------------------------------------------------------------
# Atomic transition tests
# ---------------------------------------------------------------------------

class TestAtomicTransitions:
    """State transitions are atomic (all-or-nothing)."""

    def test_closing_base_position_clears_state(self):
        """Closing the base position (matching ID) clears state."""
        from quant.state_machine import EngineState, PositionState
        from quant.events import PositionClosed
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos)
        
        # Fill references the SAME position ID (base close)
        fill = MockFill(pos_id="abc-123")
        event = PositionClosed(symbol="NIFTY", time="t0", fill=fill)
        
        new_state = apply_event(state, event)
        assert new_state.position is None  # Base position closed

    def test_closing_pyramid_does_not_clear_base(self):
        """Closing a pyramid (different ID) doesn't clear base position."""
        from quant.state_machine import EngineState, PositionState
        from quant.events import PositionClosed
        
        pos = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos)
        
        # Fill references a DIFFERENT position ID (pyramid close)
        fill = MockFill(pos_id="pyr-456")
        event = PositionClosed(symbol="NIFTY", time="t0", fill=fill)
        
        # State should be unchanged (pyramid close doesn't affect base)
        new_state = apply_event(state, event)
        assert new_state.position == pos  # Base position preserved

    def test_opening_position_when_already_open_raises(self):
        """Opening a position when one is already open raises error."""
        from quant.state_machine import EngineState, PositionState
        from quant.events import PositionOpened
        
        pos1 = PositionState(
            id="abc-123",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        state = EngineState(symbol="NIFTY", position=pos1)
        
        pos2 = PositionState(
            id="def-456",
            entry=200.0,
            size=50.0,
            sl=190.0,
            tp=210.0,
            side="SHORT",
        )
        event = PositionOpened(symbol="NIFTY", time="t0", position=pos2)
        
        with pytest.raises(ValueError, match="Position already open"):
            apply_event(state, event)

    def test_closing_nonexistent_position_raises(self):
        """Closing when no position exists raises error."""
        from quant.state_machine import EngineState
        from quant.events import PositionClosed
        
        state = EngineState(symbol="NIFTY")
        fill = MockFill()
        event = PositionClosed(symbol="NIFTY", time="t0", fill=fill)
        
        with pytest.raises(ValueError, match="No position to close"):
            apply_event(state, event)


# ---------------------------------------------------------------------------
# Sequence number tests
# ---------------------------------------------------------------------------

class TestSequenceNumbers:
    """Sequence numbers are monotonic and unique per transition."""

    def test_sequence_increments_per_event(self):
        """Each event increments sequence by 1."""
        from quant.state_machine import EngineState, Bar
        from quant.events import BarClosed
        
        state = EngineState(symbol="NIFTY")
        
        for i in range(5):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
            state = apply_event(state, event)
            assert state.sequence == i + 1

    def test_sequence_is_gap_free(self):
        """Sequence numbers have no gaps."""
        from quant.state_machine import EngineState, Bar
        from quant.events import BarClosed
        
        state = EngineState(symbol="NIFTY")
        sequences = [0]
        
        for i in range(10):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
            state = apply_event(state, event)
            sequences.append(state.sequence)
        
        # Sequences should be [0, 1, 2, 3, ..., 10]
        assert sequences == list(range(11))


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockFill:
    def __init__(self, pos_id="abc-123"):
        self.position = MockPosition(pos_id=pos_id)
        self.close_price = 95.0
        self.close_time = "t1"
        self.reason = "SL"
        self.pnl = -500.0


class MockRisk:
    def __init__(self):
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""


# ---------------------------------------------------------------------------
# Import apply_event at module level for tests
# ---------------------------------------------------------------------------

def apply_event(state, event):
    """Placeholder - will be replaced by actual implementation."""
    from quant.transitions import apply_event as _apply_event
    return _apply_event(state, event)
