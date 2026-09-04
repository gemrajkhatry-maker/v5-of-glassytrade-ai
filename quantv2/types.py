from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from quantv2.oms import Position

@dataclass(frozen=True)
class Bar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    delta: float = 0.0

@dataclass(frozen=True)
class Context:
    symbol: str
    bar: Bar
    tick: float = 0.05
    vah: float | None = None
    val: float | None = None
    poc: float | None = None
    cvd_slope: float = 0.0
    extra: dict = field(default_factory=dict)

@dataclass(frozen=True)
class Signal:
    type: str
    entry: float
    sl: float
    tp: float
    rr: float
    setup: str
    symbol: str
    timestamp: str

@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str
    signal: Signal | None = None
    position: "Position | None" = None
