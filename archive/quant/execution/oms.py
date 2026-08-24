from quant.contracts.entities import Signal
from quant.execution.order import Fill, Order, Position


class PaperOMS:
    def __init__(self) -> None:
        pass

    def submit(self, signal: Signal, quantity: float) -> Position:
        size = quantity if signal.is_buy else -quantity
        return Position(
            order=Order(signal=signal, quantity=quantity),
            open_price=float(signal.price),
            open_time=signal.timestamp,
            size=size,
        )

    def close(self, position: Position, price: float, time: str, reason: str) -> Fill:
        pnl = (price - position.open_price) * position.size
        closed = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=position.size,
            realized_pnl=pnl,
        )
        return Fill(
            position=closed,
            close_price=price,
            close_time=time,
            reason=reason,
            pnl=pnl,
        )
