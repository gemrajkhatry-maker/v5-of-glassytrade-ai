import uuid
from dataclasses import dataclass, field

from quant.decision.signal_builder import Signal
from quant.execution.trade_costs import TradeCosts


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
    entry_costs: TradeCosts | None = None  # costs charged by the entry fill

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
    pnl: float                  # authoritative net P&L for this fill
    costs: TradeCosts | None = None  # costs charged by the exit fill
    logical_id: str = ""         # durable idempotency key for this fill


def _costs_to_dict(costs: TradeCosts | None) -> dict | None:
    if costs is None:
        return None
    return {
        "slippage": costs.slippage,
        "stt": costs.stt,
        "exchange_fee": costs.exchange_fee,
        "brokerage": costs.brokerage,
        "gst": costs.gst,
        "sebi_charges": costs.sebi_charges,
        "total": costs.total,
    }


def _costs_from_dict(value) -> TradeCosts | None:
    if not value:
        return None
    return TradeCosts(**{
        key: float(value.get(key, 0.0))
        for key in ("slippage", "stt", "exchange_fee", "brokerage", "gst", "sebi_charges", "total")
    })


def position_to_row(symbol: str, position: Position, *, stop_meta: dict | None = None) -> dict:
    sig = position.order.signal
    meta = stop_meta or {}
    return {
        "id": position._id,
        "symbol": symbol,
        "side": "LONG" if position.size > 0 else "SHORT",
        "entry_price": position.open_price,
        "size": position.size,
        "stop_loss": float(meta.get("stop_loss") or sig.sl),
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
        "entry_costs": _costs_to_dict(position.entry_costs),
        "breakeven": meta.get("breakeven"),
        "trail_stop": meta.get("trail_stop"),
        "tp_tier": int(meta.get("tp_tier") or 0),
        "entry_time_epoch": float(meta.get("entry_time_epoch") or 0.0),
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
        entry_costs=_costs_from_dict(row.get("entry_costs")),
        _id=str(row.get("id") or ""),
    )
