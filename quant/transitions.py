"""Phase 2: Atomic state transitions.

Every state transition is a pure function: (State, Event) -> State.
No side effects. Deterministic. Atomic (all-or-nothing).
"""

from __future__ import annotations

from quant.state_machine import EngineState, PositionState
from quant.events import (
    Event,
    BarClosed,
    PositionOpened,
    PositionClosed,
    RiskUpdated,
)


def _position_to_state(pos) -> PositionState:
    """Convert a Position (execution.order) to PositionState (state_machine).

    Extracts the essential state fields from a Position object for storage
    in the immutable EngineState.
    """
    # If already a PositionState, return as-is
    if isinstance(pos, PositionState):
        return pos
    
    # Otherwise, extract from execution.order.Position
    sig = pos.order.signal
    return PositionState(
        id=pos._id,
        entry=float(sig.entry),
        size=float(pos.size),
        sl=float(sig.sl),
        tp=float(sig.tp),
        side="LONG" if pos.size > 0 else "SHORT",
        pyramid_level=int(getattr(pos, "pyramid_level", 0)),
        is_pyramid=bool(getattr(pos, "is_pyramid", False)),
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
            pos_id = getattr(event.position, 'id', None) or getattr(event.position, '_id', None)
            raise ValueError(
                f"Position already open: cannot open {pos_id} "
                f"while {state.position.id} is open"
            )
        pos_state = _position_to_state(event.position)
        return state.with_position(pos_state)

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
