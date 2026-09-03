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

    @property
    def id(self) -> str:
        """Public alias for ``_id`` — new code must use ``.id`` (SMELL-09)."""
        return self._id


@dataclass(frozen=True)
class Fill:
    position: Position
    close_price: float
    close_time: str
    reason: str                 # "SL" | "TP" | "TRAIL" | "TIME" | "MANUAL"
    pnl: float


def position_to_row(symbol: str, position: Position) -> dict:
    sig = position.order.signal
    return {
        "id": position._id,
        "symbol": symbol,
        "side": "LONG" if position.size > 0 else "SHORT",
        "entry_price": position.open_price,
        "size": position.size,
        "stop_loss": sig.sl,
        "take_profit": sig.tp,
        "source": sig.model_label,
        "opened_at": position.open_time,
        "entry": sig.entry,
        "reason": sig.reason,
        "rr": sig.rr,
        "timestamp": sig.timestamp,
        "type": sig.type,
        "model_label": sig.model_label,
        "quantity": position.order.quantity,
        "pyramid_level": position.pyramid_level,
        "is_pyramid": position.is_pyramid,
    }


def row_to_position(row: dict) -> Position:
    sig = Signal(
        type=str(row.get("type") or row.get("side") or "LONG"),
        reason=str(row.get("reason") or ""),
        entry=float(row.get("entry") or row.get("entry_price") or 0),
        sl=float(row.get("stop_loss") or 0),
        tp=float(row.get("take_profit") or 0),
        rr=float(row.get("rr") or 0),
        model_label=str(row.get("model_label") or row.get("source") or ""),
        symbol=str(row.get("symbol") or ""),
        timestamp=str(row.get("timestamp") or row.get("opened_at") or ""),
    )
    size = float(row.get("size") or 0)
    qty = float(row.get("quantity") or abs(size))
    return Position(
        order=Order(signal=sig, quantity=qty),
        open_price=float(row.get("entry_price") or sig.entry),
        open_time=str(row.get("opened_at") or ""),
        size=size,
        pyramid_level=int(row.get("pyramid_level") or 0),
        is_pyramid=bool(row.get("is_pyramid") or False),
        _id=str(row.get("id") or ""),
    )
