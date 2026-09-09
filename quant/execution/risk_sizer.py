from dataclasses import dataclass
from typing import Protocol

from quant.decision.intent import TradeIntent


@dataclass(frozen=True)
class ExecutableSignal:
    intent: TradeIntent
    quantity: float
    lot_size: float

    @property
    def symbol(self) -> str:
        return self.intent.symbol

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


class RiskSizer(Protocol):
    def size(self, intent: TradeIntent, *, lot_size: float) -> ExecutableSignal:
        ...


class FixedRiskSizer:
    """Minimal adapter used to establish the executable-signal boundary."""

    def __init__(self, quantity: float) -> None:
        self.quantity = quantity

    def size(self, intent: TradeIntent, *, lot_size: float) -> ExecutableSignal:
        snapped = int(self.quantity // lot_size) * lot_size
        if snapped <= 0:
            raise ValueError("quantity below one lot")
        return ExecutableSignal(intent=intent, quantity=snapped, lot_size=lot_size)
