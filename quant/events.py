"""Typed event bus for the quant runtime.

Events are frozen dataclasses that carry references to the shipped quant
types. The EventBus dispatches synchronously and in order to every handler
subscribed to an event's exact type; the QuantEngine loop drives it (no
asyncio here).

Performance: event_id uses a monotonic counter instead of UUID to avoid
the ~1-2μs overhead per event on the hot path. correlation_id is still
a UUID for cross-engine correlation when needed.
"""

from __future__ import annotations

import itertools
import uuid


from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from quant.bars import Bar
    from quant.decision.decision_service import QuantDecision
    from quant.decision.signal_builder import Signal
    from quant.execution.order import Fill, Position
    from quant.execution.risk import RiskState


@dataclass(frozen=True, kw_only=True)
class Event:
    symbol: str
    time: str
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)


@dataclass(frozen=True)
class BarClosed(Event):
    bar: "Bar"


@dataclass(frozen=True)
class DecisionProduced(Event):
    decision: "QuantDecision"


@dataclass(frozen=True)
class SignalApproved(Event):
    signal: "Signal"


@dataclass(frozen=True)
class SignalBlocked(Event):
    """An approved signal could not be routed through the OMS.

    Emitted once per blocking episode: repeats of the same (signal, side)
    blocked for the same reason are latched (debug-logged only) so the
    stream stays truthful without spamming. Never folded into engine state.
    """
    signal: "Signal"
    reason: str = ""


@dataclass(frozen=True)
class PositionOpened(Event):
    position: "Position"


@dataclass(frozen=True)
class PositionClosed(Event):
    fill: "Fill"


@dataclass(frozen=True)
class PositionReduced(Event):
    """A partial fill reduced an open position but did not close it."""
    fill: "Fill"
    remaining: "Position"


@dataclass(frozen=True)
class RiskUpdated(Event):
    risk: "RiskState"


@dataclass(frozen=True)
class DepthUpdated(Event):
    depth: dict | None = None


@dataclass(frozen=True)
class AmtUpdated(Event):
    amt: dict | None = None


@dataclass(frozen=True)
class OrderSubmitted(Event):
    """Audit trail: an order was submitted to the broker."""
    order_id: str = ""
    side: str = ""  # BUY / SELL
    quantity: float = 0.0
    price: float = 0.0
    reason: str = ""  # ENTRY / CLOSE / CLOSE_PARTIAL / EMERGENCY_HALT


@dataclass(frozen=True)
class OrderFilled(Event):
    """Audit trail: an order was filled by the broker."""
    order_id: str = ""
    fill_price: float = 0.0
    filled_qty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class StopMoved(Event):
    """Audit trail: a position's protective stop level changed (breakeven arm,
    trailing-stop ratchet, or pyramid ratchet). Emitted at the moment of change
    — not just when the moved stop is hit — so every stop move is journaled and
    replay-deterministic.

    reason ∈ {BREAKEVEN_ARMED, TRAIL_RATCHET, PYRAMID_RATCHET}
    """
    old_sl: float = 0.0
    new_sl: float = 0.0
    reason: str = ""
    # Added for position-specific folding. Empty means legacy event; replay
    # treats legacy StopMoved as a base-position move for compatibility.
    position_id: str = ""
    stop_kind: str = "TRAIL"


@dataclass(frozen=True)
class SignalProduced(Event):
    """Emitted when Strategy Gates 1-4 produce a candidate execution signal."""
    signal: Any = None
    setup_name: str = ""


@dataclass(frozen=True)
class StopLossRatchet(Event):
    """Emitted on monotonic stop adjustment."""
    old_sl: float = 0.0
    new_sl: float = 0.0
    reason: str = ""
    position_id: str = ""


@dataclass(frozen=True)
class EmergencyFlatten(Event):
    """Emitted on contingent stop placement failure or emergency circuit breaker."""
    position_id: str = ""
    reason: str = ""
    quantity: float = 0.0
    side: str = ""


@dataclass(frozen=True)
class AgentDecisionProduced(Event):
    decision: dict



Handler = Callable[[Event], None]
E = TypeVar("E", bound=Event)


class EventBus:
    """Synchronous event bus with priority support.

    Handlers are invoked in priority order (higher priority first) within
    each event type. Default priority is 0. Critical handlers (position
    tracking, risk) should use higher priority; non-critical handlers
    (journal, UI) should use lower priority.

    Threading contract: all ``subscribe`` calls happen BEFORE engines start
    their run threads; subscribing while another thread may ``publish`` is
    unsupported by design (handler lists are intentionally lock-free on the
    publish hot path). Engine-owned buses only ever see publishes from their
    own engine thread, serialized through ``QuantEngine._emit_lock``.
    """

    def __init__(self) -> None:
        # _handlers maps event type -> list of (priority, handler) tuples
        self._handlers: dict[type[Event], list[tuple[int, Handler]]] = {}
        # Per-bus monotonic counter for event IDs (avoids UUID overhead)
        self._event_id_counter = itertools.count(1)
    
    def next_event_id(self) -> str:
        """Generate the next monotonic event ID (per-bus)."""
        return str(next(self._event_id_counter))

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
        priority: int = 0,
    ) -> None:
        """Subscribe a handler to an event type with optional priority.
        
        Higher priority handlers run first. Default priority is 0.
        """
        handlers = self._handlers.setdefault(event_type, [])
        handlers.append((priority, handler))
        # Sort by priority descending (higher priority first)
        handlers.sort(key=lambda x: x[0], reverse=True)

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribed handlers.

        Handler isolation: one failing handler MUST NOT poison later handlers
        or propagate into the publisher (proven empirically: a journal disk-
        full error killed the whole engine thread because the journal
        subscriber shares this bus). Failures are logged with the event type
        so they stay visible; the event stream continues.
        """
        import logging

        if isinstance(event, AmtUpdated) and isinstance(event.amt, dict):
            # AMT DTOs contain the complete footprint history for UI/decision
            # consumers, but retaining that history in every journal/trace
            # event is quadratic in bars. Events carry only the latest candle;
            # the live analyzer remains the owner of the full snapshot.
            footprints = event.amt.get("footprints")
            if isinstance(footprints, dict) and len(footprints) > 1:
                latest_key = event.time if event.time in footprints else next(reversed(footprints))
                bounded_amt = dict(event.amt)
                bounded_amt["footprints"] = {latest_key: footprints[latest_key]}
                object.__setattr__(event, "amt", bounded_amt)

        # Events are frozen value objects, while the bus owns the per-engine
        # ordering sequence. Attach the ID at the publication boundary so
        # every public subscriber observes the same durable identity.
        if not hasattr(event, "event_id"):
            object.__setattr__(event, "event_id", self.next_event_id())
        logger = logging.getLogger(__name__)
        for _, handler in self._handlers.get(type(event), ()):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus handler %r failed for %s — continuing",
                    getattr(handler, "__name__", repr(handler)),
                    type(event).__name__,
                )
