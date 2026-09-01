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
        pos_state = _position_to_state(event.position)
        
        # Check if this is a pyramid add-on
        if pos_state.is_pyramid:
            # Pyramids are allowed when base position exists
            if state.position is None:
                raise ValueError(
                    f"Cannot open pyramid {pos_state.id} — no base position open"
                )
            # Add to pyramids tuple (immutable)
            new_pyramids = state.pyramids + (pos_state,)
            from dataclasses import replace
            return replace(state, pyramids=new_pyramids, sequence=state.sequence + 1)
        
        # Base position: no existing position allowed
        if state.position is not None:
            raise ValueError(
                f"Position already open: cannot open {pos_state.id} "
                f"while {state.position.id} is open"
            )
        return state.with_position(pos_state)

    elif isinstance(event, PositionClosed):
        # Guard: position must exist
        if state.position is None and not state.pyramids:
            raise ValueError("No position to close")
        
        # Check if this is a pyramid close (ID matches one of the pyramids)
        pyramid_ids = {p.id for p in state.pyramids}
        closed_id = getattr(event.fill.position, '_id', None) or getattr(event.fill.position, 'id', None)
        
        if closed_id in pyramid_ids:
            # Remove the pyramid from the tuple
            new_pyramids = tuple(p for p in state.pyramids if p.id != closed_id)
            from dataclasses import replace
            return replace(state, pyramids=new_pyramids, sequence=state.sequence + 1)
        
        # Base position close: ID must match
        if state.position is not None and closed_id != state.position.id:
            # Unknown ID — could be a stale pyramid close, ignore
            return state
        
        return state.without_position()

    elif isinstance(event, RiskUpdated):
        return state.with_risk(event.risk)

    else:
        # Unknown events are no-ops
        return state
