"""Typed event bus for the quant runtime.

Events are frozen dataclasses that carry references to the shipped quant
types. The EventBus dispatches synchronously and in order to every handler
subscribed to an event's exact type; the QuantEngine loop drives it (no
asyncio here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from quant.auction_state import AuctionState
    from quant.bars import Bar
    from quant.decision.decision_service import QuantDecision
    from quant.contracts.entities import Signal
    from quant.execution.order import Fill, Position
    from quant.execution.risk import RiskState


@dataclass(frozen=True)
class Event:
    symbol: str
    time: str
    # Stream metadata is keyword-only so existing positional constructors stay
    # compatible.  QuantEngine fills these fields at the single emit boundary.
    event_id: str = field(default="", kw_only=True)
    session_id: str = field(default="", kw_only=True)
    sequence: int = field(default=0, kw_only=True)
    correlation_id: str = field(default="", kw_only=True)
    causation_id: str = field(default="", kw_only=True)
    source: str = field(default="", kw_only=True)


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


Handler = Callable[[Event], None]
E = TypeVar("E", bound=Event)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = {}

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get(type(event), ()):
            handler(event)
