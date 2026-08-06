from dataclasses import dataclass

from quant.decision.signal_builder import Signal


@dataclass(frozen=True)
class Order:
    signal: Signal
    quantity: float


@dataclass(frozen=True)
class Position:
    order: Order
    open_price: float
    open_time: str
    size: float                 # signed: +long / -short
    realized_pnl: float = 0.0   # for closed positions


@dataclass(frozen=True)
class Fill:
    position: Position
    close_price: float
    close_time: str
    reason: str                 # "SL" | "TP" | "TRAIL" | "TIME" | "MANUAL"
    pnl: float
