from __future__ import annotations
from dataclasses import dataclass
from quantv2.types import Signal

@dataclass(frozen=True)
class Position:
    pid: str
    symbol: str
    side: str
    qty: float
    entry: float
    sl: float
    tp: float
    setup: str
    opened_at: str

@dataclass(frozen=True)
class Fill:
    pid: str
    qty: float
    price: float
    pnl: float
    reason: str

class PaperOMS:
    def __init__(self) -> None:
        self._n = 0

    def submit(self, signal: Signal, qty: float) -> Position:
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._n += 1
        return Position(pid=f"p{self._n}", symbol=signal.symbol, side=signal.type, qty=float(qty), entry=signal.entry, sl=signal.sl, tp=signal.tp, setup=signal.setup, opened_at=signal.timestamp)

    def close(self, pos: Position, price: float, reason: str) -> Fill:
        pnl = (price - pos.entry) * pos.qty if pos.side == "LONG" else (pos.entry - price) * pos.qty
        return Fill(pid=pos.pid, qty=pos.qty, price=price, pnl=pnl, reason=reason)
