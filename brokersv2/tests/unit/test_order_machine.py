"""Tests for Order Lifecycle State Machine."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from brokersv2.oms.order_machine import (
    OrderState,
    OrderStateMachine,
    OrderEvent,
    OrderTransitionError,
    InvalidOrderStateError,
)


class TestOrderState:
    """Test order state enum."""

    def test_state_values(self):
        """Test state enum values."""
        assert OrderState.PENDING.value == "PENDING"
        assert OrderState.SUBMITTED.value == "SUBMITTED"
        assert OrderState.PARTIAL.value == "PARTIAL"
        assert OrderState.FILLED.value == "FILLED"
        assert OrderState.CANCELLED.value == "CANCELLED"
        assert OrderState.REJECTED.value == "REJECTED"

    def test_terminal_states(self):
        """Test terminal state detection."""
        assert OrderState.FILLED.is_terminal is True
        assert OrderState.CANCELLED.is_terminal is True
        assert OrderState.REJECTED.is_terminal is True
        
        assert OrderState.PENDING.is_terminal is False
        assert OrderState.SUBMITTED.is_terminal is False
        assert OrderState.PARTIAL.is_terminal is False


class TestOrderEvent:
    """Test order events."""

    def test_submit_event(self):
        """Test order submit event."""
        event = OrderEvent.SUBMIT
        assert event == OrderEvent.SUBMIT

    def test_ack_event(self):
        """Test order acknowledge event."""
        event = OrderEvent.ACK
        assert event == OrderEvent.ACK

    def test_fill_event(self):
        """Test fill event."""
        event = OrderEvent.FILL
        assert event == OrderEvent.FILL

    def test_partial_fill_event(self):
        """Test partial fill event."""
        event = OrderEvent.PARTIAL_FILL
        assert event == OrderEvent.PARTIAL_FILL

    def test_cancel_event(self):
        """Test cancel event."""
        event = OrderEvent.CANCEL
        assert event == OrderEvent.CANCEL

    def test_reject_event(self):
        """Test reject event."""
        event = OrderEvent.REJECT
        assert event == OrderEvent.REJECT


class TestOrderStateMachine:
    """Test order state machine transitions."""

    def test_initial_state(self):
        """Test initial state is PENDING."""
        machine = OrderStateMachine(order_id="ORD001")
        assert machine.current_state == OrderState.PENDING

    def test_submit_transition(self):
        """Test PENDING → SUBMITTED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        assert machine.current_state == OrderState.SUBMITTED

    def test_ack_transition(self):
        """Test SUBMITTED → ACKNOWLEDGED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.ACK)
        assert machine.current_state == OrderState.SUBMITTED  # ACK keeps it submitted

    def test_partial_fill_transition(self):
        """Test SUBMITTED → PARTIAL transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.PARTIAL_FILL)
        assert machine.current_state == OrderState.PARTIAL

    def test_full_fill_from_submitted(self):
        """Test SUBMITTED → FILLED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        assert machine.current_state == OrderState.FILLED

    def test_full_fill_from_partial(self):
        """Test PARTIAL → FILLED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.PARTIAL_FILL)
        machine.transition(OrderEvent.FILL)
        assert machine.current_state == OrderState.FILLED

    def test_cancel_from_submitted(self):
        """Test SUBMITTED → CANCELLED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.CANCEL)
        assert machine.current_state == OrderState.CANCELLED

    def test_cancel_from_partial(self):
        """Test PARTIAL → CANCELLED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.PARTIAL_FILL)
        machine.transition(OrderEvent.CANCEL)
        assert machine.current_state == OrderState.CANCELLED

    def test_reject_from_submitted(self):
        """Test SUBMITTED → REJECTED transition."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.REJECT)
        assert machine.current_state == OrderState.REJECTED

    def test_invalid_transition_pending_to_fill(self):
        """Test invalid transition: PENDING → FILLED (must submit first)."""
        machine = OrderStateMachine(order_id="ORD001")
        
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.FILL)

    def test_invalid_transition_pending_to_cancel(self):
        """Test invalid transition: PENDING → CANCELLED (must submit first)."""
        machine = OrderStateMachine(order_id="ORD001")
        
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.CANCEL)

    def test_invalid_transition_filled_to_any(self):
        """Test invalid transitions from FILLED (terminal state)."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        
        # All transitions from FILLED should fail
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.CANCEL)
        
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.SUBMIT)

    def test_invalid_transition_cancelled_to_any(self):
        """Test invalid transitions from CANCELLED (terminal state)."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.CANCEL)
        
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.SUBMIT)

    def test_invalid_transition_rejected_to_any(self):
        """Test invalid transitions from REJECTED (terminal state)."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.REJECT)
        
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.SUBMIT)

    def test_state_history(self):
        """Test state history tracking."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.PARTIAL_FILL)
        machine.transition(OrderEvent.FILL)
        
        history = machine.get_history()
        
        assert len(history) == 4  # PENDING → SUBMITTED → PARTIAL → FILLED
        assert history[0].to_state == OrderState.PENDING
        assert history[1].to_state == OrderState.SUBMITTED
        assert history[2].to_state == OrderState.PARTIAL
        assert history[3].to_state == OrderState.FILLED

    def test_state_history_with_timestamps(self):
        """Test state history includes timestamps."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        
        history = machine.get_history()
        
        assert len(history) == 2
        assert history[0].timestamp is not None
        assert history[1].timestamp is not None

    def test_is_terminal_state(self):
        """Test terminal state detection."""
        machine = OrderStateMachine(order_id="ORD001")
        assert machine.is_terminal is False
        
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        assert machine.is_terminal is True

    def test_can_transition(self):
        """Test can_transition check."""
        machine = OrderStateMachine(order_id="ORD001")
        
        # PENDING can submit
        assert machine.can_transition(OrderEvent.SUBMIT) is True
        
        # PENDING cannot fill
        assert machine.can_transition(OrderEvent.FILL) is False
        
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        
        # FILLED cannot transition
        assert machine.can_transition(OrderEvent.CANCEL) is False

    def test_time_in_state(self):
        """Test time spent in current state."""
        machine = OrderStateMachine(order_id="ORD001")
        
        # Should be very small time in PENDING
        time_in_state = machine.time_in_state()
        assert time_in_state >= 0
        assert time_in_state < 1.0  # Less than 1 second

    def test_reset_machine(self):
        """Test resetting state machine."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        
        machine.reset()
        
        assert machine.current_state == OrderState.PENDING
        assert len(machine.get_history()) == 1  # Only initial PENDING

    def test_multiple_fills_not_allowed(self):
        """Test that multiple FILL events after FILLED state fail."""
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        
        # Second fill should fail
        with pytest.raises(OrderTransitionError):
            machine.transition(OrderEvent.FILL)

    def test_valid_transitions_matrix(self):
        """Test all valid transitions."""
        # PENDING → SUBMIT → SUBMITTED
        machine = OrderStateMachine(order_id="ORD001")
        machine.transition(OrderEvent.SUBMIT)
        assert machine.current_state == OrderState.SUBMITTED
        
        # SUBMITTED → PARTIAL_FILL → PARTIAL
        machine.transition(OrderEvent.PARTIAL_FILL)
        assert machine.current_state == OrderState.PARTIAL
        
        # PARTIAL → FILL → FILLED
        machine.transition(OrderEvent.FILL)
        assert machine.current_state == OrderState.FILLED

    def test_order_id_tracking(self):
        """Test order ID is tracked."""
        machine = OrderStateMachine(order_id="TEST_ORD_123")
        assert machine.order_id == "TEST_ORD_123"
