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

from quant.contracts.timezones import epoch_to_iso
from quant.state_machine import EngineState, PositionState
from quant.events import (
    Event,
    BarClosed,
    PositionOpened,
    PositionClosed,
    PositionReduced,
    RiskUpdated,
    StopMoved,
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
    sig = getattr(pos, "order", None) and getattr(pos.order, "signal", None)
    entry_time = str(
        getattr(pos, "open_time", "")
        or getattr(pos, "entry_time", "")
        or (sig.timestamp if sig else "")
        or ""
    )
    return PositionState(
        id=pos._id,
        entry=float(sig.entry) if sig else float(getattr(pos, "open_price", 0.0) or getattr(pos, "entry_price", 0.0)),
        size=float(pos.size),
        sl=float(sig.sl) if sig else float(getattr(pos, "stop_loss", 0.0)),
        tp=float(sig.tp) if sig else float(getattr(pos, "take_profit", 0.0)),
        side="LONG" if pos.size > 0 else "SHORT",
        pyramid_level=int(getattr(pos, "pyramid_level", 0)),
        is_pyramid=bool(getattr(pos, "is_pyramid", False)),
        entry_time=entry_time,
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


def _build_closed_trade_dto(fill, time_str: str = "") -> dict:
    """Build a closed trade DTO for the chart and portfolio history."""
    pos = getattr(fill, "position", None)
    pos_id = str(getattr(pos, "_id", None) or getattr(pos, "id", "") or "")
    sig = getattr(pos, "order", None) and getattr(pos.order, "signal", None)
    side = getattr(pos, "side", "") or (sig.type if sig else ("LONG" if getattr(pos, "size", 0) > 0 else "SHORT"))
    entry_px = float(getattr(pos, "open_price", 0.0) or getattr(pos, "entry_price", 0.0) or (sig.entry if sig else 0.0))
    size_val = float(getattr(pos, "size", 0.0))
    sl = float(getattr(pos, "stop_loss", 0.0) or (sig.sl if sig else 0.0))
    tp = float(getattr(pos, "take_profit", 0.0) or (sig.tp if sig else 0.0))
    pnl_val = float(getattr(fill, "pnl", 0.0))
    open_t = str(getattr(pos, "open_time", "") or getattr(pos, "entry_time", "") or (sig.timestamp if sig else "") or "")
    close_t = str(getattr(fill, "close_time", "") or time_str or "")
    close_px = float(getattr(fill, "close_price", 0.0))
    reason = str(getattr(fill, "reason", "EXIT"))

    return {
        "id": pos_id,
        "symbol": str(getattr(pos, "symbol", "") or (sig.symbol if sig else "")),
        "side": side,
        "source": "AMT",
        "entryPrice": entry_px,
        "size": size_val,
        "stopLoss": sl,
        "takeProfit": tp,
        "pnl": pnl_val,
        "entryTime": epoch_to_iso(open_t),
        "status": "CLOSED",
        "exitPrice": close_px,
        "exitTime": epoch_to_iso(close_t),
        "closeReason": reason,
    }


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
        if not isinstance(event.position, PositionState) and not pos_state.entry_time and getattr(event, "time", None):
            pos_state = replace(pos_state, entry_time=epoch_to_iso(event.time))

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
        #
        # STOP MERGE (review finding, CRITICAL): the surviving execution
        # Position object carries only its SUBMITTED stop (derived from
        # ``sig.sl`` by ``_position_to_state``), while the ratcheted stop lives
        # in this event-fold authority (folded from StopMoved). Blindly
        # replacing the position with the re-derived one erased every ratchet
        # on the first partial. Merge monotonically so a partial can never
        # widen a tightened stop.
        remaining = event.remaining
        rem_id = getattr(remaining, "_id", None) or getattr(remaining, "id", None)

        def _merge_stop(new_state: PositionState, existing: PositionState) -> PositionState:
            if existing is None or float(existing.sl) <= 0:
                return new_state
            if str(existing.side).upper() == "LONG":
                sl = max(float(existing.sl), float(new_state.sl))
            else:
                sl = min(float(existing.sl), float(new_state.sl))
            return replace(new_state, sl=sl)

        if state.position is not None and rem_id == state.position.id:
            return state.with_position(
                _merge_stop(_position_to_state(remaining), state.position)
            )
        pyramid_ids = {p.id for p in state.pyramids}
        if rem_id in pyramid_ids:
            new_pyramids = tuple(
                _merge_stop(_position_to_state(remaining), p) if p.id == rem_id else p
                for p in state.pyramids
            )
            return replace(state, pyramids=new_pyramids, sequence=state.sequence + 1)
        # Unknown id — fold never raises on an unmatched reduce (replay of a
        # stale/foreign partial must not poison the chain).
        return state

    elif isinstance(event, PositionClosed):
        closed_id = _close_id(event.fill)
        realized = state.realized_pnl + float(event.fill.pnl)
        closed_dto = _build_closed_trade_dto(event.fill, getattr(event, "time", ""))
        new_closed = (state.closed_trades + (closed_dto,))[-50:]

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
                closed_trades=new_closed,
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
        return replace(
            state.without_position(),
            realized_pnl=realized,
            closed_trades=new_closed,
        )

    elif isinstance(event, StopMoved):
        # Fold the protective-stop move into the position it belongs to.
        # StopMoved is emitted on every ratchet (breakeven arm, trail ratchet,
        # pyramid base-SL ratchet) but was never applied to the event-fold
        # authority, so the portfolio row and the operator's displayed Trail SL
        # kept the SUBMITTED stop while ExitEngine enforced the tighter
        # ratcheted one — three different stops for one trade.
        #
        # SCOPE (review finding 2, IMPORTANT): StopMoved carries NO position
        # id, and all three emitters describe the BASE position's stop —
        # ``_emit_stop_moves`` reads ``position.order.signal.sl`` of the base
        # (position_manager.py:98-118) and the pyramid ratchet emits the new
        # BASE stop (position_manager.py:657, with base_override set at
        # :649-656). ExitEngine only ever evaluates the base position
        # (position_manager.py:183); pyramid legs carry their add-time stop and
        # are closed with the base, never stop-enforced per leg. Applying the
        # move to every open leg was therefore an over-reach that silently
        # tightened legs the event never mentioned. Scoped to the base only;
        # a per-leg Move would need a leg id the event does not yet carry.
        pos = state.position
        if pos is None:
            return state
        new_sl = float(event.new_sl)
        if new_sl <= 0:
            return state
        long = str(pos.side).upper() == "LONG"
        # Monotonic: a move may only tighten, never loosen, so a replayed
        # or stale move cannot widen an already-ratcheted stop.
        if (long and new_sl <= float(pos.sl)) or (not long and new_sl >= float(pos.sl)):
            return state
        return replace(
            state,
            position=replace(pos, sl=new_sl),
            sequence=state.sequence + 1,
        )

    elif isinstance(event, RiskUpdated):
        return state.with_risk(event.risk)

    else:
        # Unknown events are no-ops
        return state