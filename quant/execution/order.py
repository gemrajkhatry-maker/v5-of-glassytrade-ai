import uuid
from dataclasses import dataclass, field

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
    realized_pnl: float = 0.0  # for closed positions
    pyramid_level: int = 0     # 0 = base trade, 1 = Pyramid 1, 2 = Pyramid 2
    is_pyramid: bool = False   # True for add-on positions (P1, P2)
    _id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False, repr=False)


@dataclass(frozen=True)
class Fill:
    position: Position
    close_price: float
    close_time: str
    reason: str                 # "SL" | "TP" | "TRAIL" | "TIME" | "MANUAL"
    pnl: float
