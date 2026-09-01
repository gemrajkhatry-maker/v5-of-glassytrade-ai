"""Phase 2: Atomic state transitions.

Every state transition is a pure function: (State, Event) -> State.
No side effects. Deterministic. Atomic (all-or-nothing).
"""

from __future__ import annotations

from quant.state_machine import EngineState
from quant.events import (
    Event,
    BarClosed,
    PositionOpened,
    PositionClosed,
    RiskUpdated,
)


def apply_event(state: EngineState, event: Event) -> EngineState:
    """Apply an event to state. Pure function. No side effects.
    
    Args:
        state: Current engine state (immutable)
        event: Event to apply (immutable)
    
    Returns:
        New engine state after applying event
    
    Raises:
        ValueError: If transition is invalid (e.g., position ID mismatch)
    """
    if isinstance(event, BarClosed):
        return state.with_bar(event.bar)
    
    elif isinstance(event, PositionOpened):
        # Guard: no existing position
        if state.position is not None:
            raise ValueError(
                f"Position already open: cannot open {event.position.id} "
                f"while {state.position.id} is open"
            )
        return state.with_position(event.position)
    
    elif isinstance(event, PositionClosed):
        # Guard: position must exist
        if state.position is None:
            raise ValueError("No position to close")
        # Guard: position ID must match
        if event.fill.position._id != state.position.id:
            raise ValueError(
                f"Position ID mismatch: event references {event.fill.position._id} "
                f"but state has {state.position.id}"
            )
        return state.without_position()
    
    elif isinstance(event, RiskUpdated):
        return state.with_risk(event.risk)
    
    else:
        # Unknown events are no-ops
        return state
