"""Order Lifecycle State Machine - manages order state transitions."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class OrderState(Enum):
    """Order lifecycle states."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        """Check if state is terminal (no further transitions allowed)."""
        return self in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED)


class OrderEvent(Enum):
    """Order state transition events."""
    SUBMIT = "SUBMIT"
    ACK = "ACK"
    FILL = "FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    CANCEL = "CANCEL"
    REJECT = "REJECT"


class OrderTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class InvalidOrderStateError(Exception):
    """Raised when order state is invalid for operation."""
    pass


@dataclass(frozen=True)
class StateTransition:
    """Record of a state transition."""
    order_id: str
    from_state: OrderState
    to_state: OrderState
    event: OrderEvent
    timestamp: datetime
    reason: Optional[str] = None


# Valid transition map: (current_state, event) -> next_state
VALID_TRANSITIONS = {
    (OrderState.PENDING, OrderEvent.SUBMIT): OrderState.SUBMITTED,
    (OrderState.SUBMITTED, OrderEvent.ACK): OrderState.SUBMITTED,
    (OrderState.SUBMITTED, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.SUBMITTED, OrderEvent.PARTIAL_FILL): OrderState.PARTIAL,
    (OrderState.SUBMITTED, OrderEvent.CANCEL): OrderState.CANCELLED,
    (OrderState.SUBMITTED, OrderEvent.REJECT): OrderState.REJECTED,
    (OrderState.PARTIAL, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.PARTIAL, OrderEvent.PARTIAL_FILL): OrderState.PARTIAL,
    (OrderState.PARTIAL, OrderEvent.CANCEL): OrderState.CANCELLED,
    (OrderState.PARTIAL, OrderEvent.REJECT): OrderState.REJECTED,
}


class OrderStateMachine:
    """
    Manages order lifecycle state transitions.
    
    State Machine:
    ```
    PENDING → SUBMITTED → FILLED
                      ↘ PARTIAL → FILLED
                            ↘ CANCELLED
                      ↘ REJECTED
                      ↘ CANCELLED
    ```
    
    Features:
    - Strict state transition validation
    - Transition history tracking
    - Terminal state enforcement
    - Time-in-state metrics
    """

    def __init__(self, order_id: str):
        """
        Initialize order state machine.
        
        Args:
            order_id: Unique order identifier
        """
        self._order_id = order_id
        self._current_state = OrderState.PENDING
        self._history: List[StateTransition] = []
        self._created_at = datetime.now(timezone.utc)
        self._state_changed_at = self._created_at

        # Record initial state
        self._history.append(
            StateTransition(
                order_id=order_id,
                from_state=OrderState.PENDING,
                to_state=OrderState.PENDING,
                event=OrderEvent.SUBMIT,  # Initial event
                timestamp=self._created_at,
                reason="Order created",
            )
        )

    @property
    def order_id(self) -> str:
        """Get order ID."""
        return self._order_id

    @property
    def current_state(self) -> OrderState:
        """Get current order state."""
        return self._current_state

    @property
    def is_terminal(self) -> bool:
        """Check if order is in terminal state."""
        return self._current_state.is_terminal

    def transition(self, event: OrderEvent, reason: Optional[str] = None) -> OrderState:
        """
        Transition order state based on event.
        
        Args:
            event: Transition event
            reason: Optional reason for transition
            
        Returns:
            New order state
            
        Raises:
            OrderTransitionError: If transition is invalid
        """
        # Check if transition is valid
        transition_key = (self._current_state, event)
        
        if transition_key not in VALID_TRANSITIONS:
            raise OrderTransitionError(
                f"Invalid transition: {self._current_state.value} + {event.value} "
                f"(current state: {self._current_state.value}, "
                f"event: {event.value})"
            )

        # Check if already in terminal state
        if self._current_state.is_terminal:
            raise OrderTransitionError(
                f"Cannot transition from terminal state: {self._current_state.value}"
            )

        # Perform transition
        old_state = self._current_state
        new_state = VALID_TRANSITIONS[transition_key]
        
        self._current_state = new_state
        self._state_changed_at = datetime.now(timezone.utc)

        # Record transition
        transition = StateTransition(
            order_id=self._order_id,
            from_state=old_state,
            to_state=new_state,
            event=event,
            timestamp=self._state_changed_at,
            reason=reason,
        )
        self._history.append(transition)

        logger.debug(
            f"Order {self._order_id}: {old_state.value} → {new_state.value} "
            f"(event: {event.value})"
        )

        return new_state

    def can_transition(self, event: OrderEvent) -> bool:
        """
        Check if transition is valid.
        
        Args:
            event: Transition event
            
        Returns:
            True if transition is valid
        """
        transition_key = (self._current_state, event)
        return transition_key in VALID_TRANSITIONS

    def get_history(self) -> List[StateTransition]:
        """Get full state transition history."""
        return list(self._history)

    def time_in_state(self) -> float:
        """
        Get time spent in current state (seconds).
        
        Returns:
            Seconds in current state
        """
        now = datetime.now(timezone.utc)
        return (now - self._state_changed_at).total_seconds()

    def reset(self):
        """Reset state machine to initial state."""
        self._current_state = OrderState.PENDING
        self._state_changed_at = datetime.now(timezone.utc)
        self._history = [
            StateTransition(
                order_id=self._order_id,
                from_state=OrderState.PENDING,
                to_state=OrderState.PENDING,
                event=OrderEvent.SUBMIT,
                timestamp=self._state_changed_at,
                reason="State machine reset",
            )
        ]

        logger.info(f"Order {self._order_id}: State machine reset")

    def __repr__(self) -> str:
        return (
            f"OrderStateMachine(order_id='{self._order_id}', "
            f"state={self._current_state.value})"
        )
