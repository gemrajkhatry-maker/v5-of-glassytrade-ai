from quant.decision.signal_builder import Signal
from quant.execution.order import Fill, Order, Position


class PaperOMS:
    """Paper order manager — mirrors live broker fill semantics.

    ``lot_size`` (units per lot, from the broker) makes the paper P&L match
    live rupee P&L exactly: the position size is snapped to lot multiples the
    same way ``DhanBrokerAdapter._resolve_quantity`` and
    ``Portfolio.open_position`` do (``round(size / lot_size) * lot_size``,
    minimum one lot), so ``pnl = price_diff * size`` uses the same unit count
    a live fill would report. Default 1.0 keeps equities/legacy semantics.
    """

    def __init__(self, lot_size: float = 1.0) -> None:
        self._lot_size = lot_size

    @staticmethod
    def _snap_to_lot(quantity: float, lot_size: float) -> float:
        """Round a raw unit count to the nearest lot multiple (min 1 lot)."""
        if lot_size is None or lot_size <= 0 or quantity <= 0:
            return quantity
        num_lots = max(1.0, round(quantity / lot_size))
        return num_lots * lot_size

    def submit(self, signal: Signal, quantity: float) -> Position:
        size = self._snap_to_lot(quantity, self._lot_size)
        signed = size if signal.type == "LONG" else -size
        return Position(
            order=Order(signal=signal, quantity=size),
            open_price=signal.entry,
            open_time=signal.timestamp,
            size=signed,
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
