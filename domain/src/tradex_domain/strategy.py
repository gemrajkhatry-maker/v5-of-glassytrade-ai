"""Strategy and scanner objects (FDS 05 §6.6/§6.8, decision D-12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from tradex_domain.clock import Clock
from tradex_domain.enums import OrderSide
from tradex_domain.execution import Position
from tradex_domain.instruments import Instrument
from tradex_domain.protocols import SessionFacade
from tradex_domain.serialization import Serializable
from tradex_domain.value_objects import Money, Quantity


@dataclass(frozen=True, slots=True)
class Signal(Serializable):
    instrument: Instrument
    direction: OrderSide
    strength: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    #: UTC timestamp of the event that produced this signal. ``None`` keeps
    #: hand-built signals backward-compatible; time-aware engines (backtest,
    #: replay) use it to align fills to the correct bar instead of matching
    #: signals to candles sequentially.
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class StrategyContext(Serializable):
    """Context passed to strategy callbacks."""

    session: SessionFacade | None = None
    instruments: tuple[Instrument, ...] = ()
    positions: tuple[Position, ...] = ()
    position: Position | None = None
    balance: Money | None = None
    timestamp: datetime | None = None
    #: Engine clock — deterministic ``TestClock`` in backtest/replay (advanced
    #: to the simulated instant), ``SystemClock`` in live/paper. Not
    #: serialized; ``None`` in hand-built contexts.
    clock: Clock | None = field(default=None, repr=False)
    bar_count: int = 0


@dataclass(frozen=True, slots=True)
class Condition(Serializable):
    """Scanner condition shape (D-12): no ``Any`` in public contracts."""

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    operator: str = ">"
    threshold: float | int | None = None


@dataclass(frozen=True, slots=True)
class ScannerDefinition(Serializable):
    universe: list[Instrument] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    rank_by: str = "score"
    limit: int = 20


@dataclass(frozen=True, slots=True)
class ScannerResult(Serializable):
    instrument: Instrument
    score: float
    matched_conditions: list[str]
    indicator_values: dict[str, float]
    rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Sizer(Protocol):
    """Position-sizing contract: turns a ``Signal`` into an order ``Quantity``."""

    def size(self, signal: Signal) -> Quantity: ...


class SignalStrengthSizer:
    """Legacy default: the absolute signal strength IS the order quantity.

    Kept as the default so existing strategies/backtests size identically to
    the historical behavior. Strategies that size by risk should inject a
    proper ``Sizer`` instead of encoding quantity in ``strength``.
    """

    def size(self, signal: Signal) -> Quantity:
        qty = abs(signal.strength) if signal.strength else 1.0
        return Quantity(value=Decimal(str(qty)))


class FixedSizer:
    """Fixed order quantity regardless of signal strength."""

    def __init__(self, quantity: Decimal | int | float | str = Decimal("1")) -> None:
        self._quantity = Quantity(value=Decimal(str(quantity)))

    def size(self, signal: Signal) -> Quantity:
        return self._quantity


__all__ = [
    "Condition",
    "FixedSizer",
    "ScannerDefinition",
    "ScannerResult",
    "Signal",
    "SignalStrengthSizer",
    "Sizer",
    "StrategyContext",
]
