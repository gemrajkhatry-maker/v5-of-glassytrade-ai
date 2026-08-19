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
    from quant.auction_state import AuctionState
    from quant.bars import Bar
    from quant.decision.decision_service import QuantDecision
    from quant.decision.signal_builder import Signal
    from quant.execution.order import Fill, Position
    from quant.execution.risk import RiskState


# Monotonic counter for event IDs — avoids UUID overhead on the hot path.
# Each event gets a unique, incrementing integer string.
_event_id_counter = itertools.count(1)


def _next_event_id() -> str:
    """Generate the next monotonic event ID."""
    return str(next(_event_id_counter))


@dataclass(frozen=True, kw_only=True)
class Event:
    symbol: str
    time: str
    event_id: str = field(default_factory=_next_event_id, compare=False)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)


@dataclass(frozen=True)
class BarClosed(Event):
    bar: "Bar"


@dataclass(frozen=True)
class AuctionUpdated(Event):
    auction: "AuctionState"


@dataclass(frozen=True)
class DecisionProduced(Event):
    decision: "QuantDecision"


@dataclass(frozen=True)
class SignalApproved(Event):
    signal: "Signal"


@dataclass(frozen=True)
class PositionOpened(Event):
    position: "Position"


@dataclass(frozen=True)
class PositionClosed(Event):
    fill: "Fill"


@dataclass(frozen=True)
class RiskUpdated(Event):
    risk: "RiskState"


@dataclass(frozen=True)
class DepthUpdated(Event):
    depth: dict | None = None


@dataclass(frozen=True)
class AmtUpdated(Event):
    amt: dict | None = None


Handler = Callable[[Event], None]
E = TypeVar("E", bound=Event)


class EventBus:
    """Synchronous event bus with priority support.
    
    Handlers are invoked in priority order (higher priority first) within
    each event type. Default priority is 0. Critical handlers (position
    tracking, risk) should use higher priority; non-critical handlers
    (journal, UI) should use lower priority.
    """

    def __init__(self) -> None:
        # _handlers maps event type -> list of (priority, handler) tuples
        self._handlers: dict[type[Event], list[tuple[int, Handler]]] = {}

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
        """Publish an event to all subscribed handlers."""
        for _, handler in self._handlers.get(type(event), ()):
            handler(event)
