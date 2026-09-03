"""Phase 2: Atomic state transitions.

Every state transition is a pure function: (State, Event) -> State.
No side effects. Deterministic. Atomic (all-or-nothing).

Validation contract (hardened): malformed or impossible payloads are
REJECTED with ``ValueError`` instead of silently poisoning state:

- Position entries must be finite (NaN/Inf are refused — NaN breaks every
  comparison, Inf overflows P&L arithmetic).
- Position sizes must be non-zero (zero-size positions divide by zero later).
- Bars must not carry negative prices (impossible for the traded instruments).
- ``PositionClosed`` requires a fill with a position that carries an id.
- A close whose id matches neither the open base nor a pyramid is a real
  invariant violation (event-production bug or reordering) and raises rather
  than silently leaving the position open forever.
- A repeated ``PositionOpened`` of the SAME id is a replay and is idempotent
  (no-op), while a second open of a DIFFERENT id while a base is open raises.
"""

from __future__ import annotations

import math
from dataclasses import replace

from quant.state_machine import EngineState, PositionState
from quant.events import (
    Event,
    BarClosed,
    PositionOpened,
    PositionClosed,
    PositionReduced,
    RiskUpdated,
)


def _validate_position_payload(pos) -> None:
    """Validate a position payload before it can enter the state machine.

    Raises ValueError for NaN/Inf entries and zero sizes. PositionState
    (the legacy value-object shape) carries entry/size directly; execution
    Positions require an order with a signal.
    """
    if pos is None:
        raise ValueError("Position event requires a position (got None)")
    if isinstance(pos, PositionState):
        entry = float(pos.entry)
        size = float(pos.size)
        pos_id = pos.id or "?"
    else:
        order = getattr(pos, "order", None)
        if order is None or getattr(order, "signal", None) is None:
            raise ValueError("Position event requires an order with a signal")
        entry = float(order.signal.entry)
        size = float(pos.size)
        pos_id = str(getattr(pos, "_id", None) or getattr(pos, "id", None) or "?")
    if math.isnan(entry):
        raise ValueError(f"Position entry price is NaN — refusing to open {pos_id}")
    if math.isinf(entry):
        raise ValueError(
            f"Position entry price is not finite (inf) — refusing to open {pos_id}"
        )
    if size == 0.0:
        raise ValueError(f"Position size must be non-zero — refusing to open {pos_id}")


def _position_to_state(pos) -> PositionState:
    """Convert a Position (execution.order) to PositionState (state_machine).

    Extracts the essential state fields from a Position object for storage
    in the immutable EngineState. Validates the payload first — malformed
    positions raise ValueError instead of entering the fold.
    """
    # If already a PositionState, return as-is
    if isinstance(pos, PositionState):
        _validate_position_payload(pos)
        return pos

    # Otherwise, extract from execution.order.Position
    _validate_position_payload(pos)
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


def _close_id(fill) -> str | None:
    """Extract the position id from a PositionClosed fill, validating shape."""
    if fill is None:
        raise ValueError("PositionClosed requires a fill (got None)")
    fill_pos = getattr(fill, "position", None)
    if fill_pos is None:
        raise ValueError("PositionClosed requires fill.position (got None)")
    closed_id = getattr(fill_pos, "_id", None) or getattr(fill_pos, "id", None)
    if closed_id is None:
        raise ValueError("PositionClosed fill.position has no id")
    return closed_id


def apply_event(state: EngineState, event: Event) -> EngineState:
    """Apply an event to state. Pure function. No side effects.

    Args:
        state: Current engine state (immutable)
        event: Event to apply (immutable)

    Returns:
        New engine state after applying event

    Raises:
        ValueError: If the payload is malformed or the transition is invalid
            (e.g., position ID mismatch, double-open of a different id).
    """
    if isinstance(event, BarClosed):
        bar = event.bar
        if bar is not None:
            for price in (bar.open, bar.high, bar.low, bar.close):
                if price is not None and price < 0:
                    raise ValueError(
                        f"Bar contains negative price {price} — refusing to fold"
                    )
        return state.with_bar(bar)

    elif isinstance(event, PositionOpened):
        pos_state = _position_to_state(event.position)

        # Check if this is a pyramid add-on
        if pos_state.is_pyramid:
            # Pyramids are allowed when base position exists
            if state.position is None:
                raise ValueError(
                    f"Cannot open pyramid {pos_state.id} — no base position open"
                )
            # Same-id replay of a pyramid open is a no-op (idempotent).
            if pos_state.id in {p.id for p in state.pyramids}:
                return state
            # Add to pyramids tuple (immutable)
            new_pyramids = state.pyramids + (pos_state,)
            return replace(state, pyramids=new_pyramids, sequence=state.sequence + 1)

        # Base position: no existing position allowed
        if state.position is not None:
            if pos_state.id == state.position.id:
                # Replayed/duplicate open of the SAME position id — idempotent
                # no-op so a replay never crashes the fold.
                return state
            raise ValueError(
                f"Position already open: cannot open {pos_state.id} "
                f"while {state.position.id} is open"
            )
        return state.with_position(pos_state)

    elif isinstance(event, PositionReduced):
        # Tiered-TP partial fill: shrink the open position (or pyramid) to the
        # surviving size while keeping its identity. Without this fold the
        # EngineState carried the ORIGINAL full size after every partial, so
        # the event-fold authority disagreed with PositionManager (execution
        # truth) and periodic_reconcile could not observe the drift.
        remaining = event.remaining
        rem_id = getattr(remaining, "_id", None) or getattr(remaining, "id", None)
        if state.position is not None and rem_id == state.position.id:
            return state.with_position(_position_to_state(remaining))
        pyramid_ids = {p.id for p in state.pyramids}
        if rem_id in pyramid_ids:
            new_pyramids = tuple(
                _position_to_state(remaining) if p.id == rem_id else p
                for p in state.pyramids
            )
            return replace(state, pyramids=new_pyramids, sequence=state.sequence + 1)
        # Unknown id — fold never raises on an unmatched reduce (replay of a
        # stale/foreign partial must not poison the chain).
        return state

    elif isinstance(event, PositionClosed):
        closed_id = _close_id(event.fill)
        realized = state.realized_pnl + float(event.fill.pnl)

        # Pyramid close: ID matches one of the pyramids.
        pyramid_ids = {p.id for p in state.pyramids}
        if closed_id in pyramid_ids:
            # Remove the pyramid from the tuple
            new_pyramids = tuple(p for p in state.pyramids if p.id != closed_id)
            return replace(
                state,
                pyramids=new_pyramids,
                sequence=state.sequence + 1,
                realized_pnl=realized,
            )

        # Base position close: ID must match.
        if state.position is None:
            raise ValueError("No position to close")
        if closed_id != state.position.id:
            raise ValueError(
                f"PositionClosed id {closed_id!r} does not match open "
                f"position {state.position.id!r} — close would be silently "
                f"dropped otherwise"
            )
        return replace(state.without_position(), realized_pnl=realized)

    elif isinstance(event, RiskUpdated):
        return state.with_risk(event.risk)

    else:
        # Unknown events are no-ops
        return state