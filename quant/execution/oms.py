from quant.decision.signal_builder import Signal
from quant.execution.order import Fill, Order, Position
from quant.execution.ports import IOMS


class PaperOMS:
    """Paper order manager — implements IOMS for simulated fills.

    Used for replay / backtest / paper trading. The coordinator injects this
    as the default OMS; ``LiveOMS`` is injected when env=live.

    ``lot_size`` (units per lot, from the broker) makes the paper P&L match
    live rupee P&L exactly: the position size is snapped to lot multiples the
    same way ``DhanBrokerAdapter._resolve_quantity`` and
    ``Portfolio.open_position`` do (``round(size / lot_size) * lot_size``,
    minimum one lot), so ``pnl = price_diff * size`` uses the same unit count
    a live fill would report. Default 1.0 keeps equities/legacy semantics.
    """

    def __init__(self, lot_size: float = 1.0) -> None:
        self._lot_size = lot_size

    @property
    def lot_size(self) -> float:
        return self._lot_size

    @staticmethod
    def _snap_to_lot(quantity: float, lot_size: float) -> float:
        """Round a raw unit count to the nearest lot multiple (min 1 lot).

        Half-lots round UP: banker's rounding (round(2.5)=2) silently
        under-sized pyramid P2 by 20% (certification S10 finding)."""
        if lot_size is None or lot_size <= 0 or quantity <= 0:
            return quantity
        import math

        num_lots = max(1.0, math.floor(quantity / lot_size + 0.5))
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
        # Preserve the original position's _id so close events can be matched
        # to the state's position (prevents double-close false positives)
        original_id = getattr(position, '_id', None)
        closed = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=position.size,
            realized_pnl=pnl,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
            _id=original_id,  # Preserve original ID
        )
        return Fill(
            position=closed,
            close_price=price,
            close_time=time,
            reason=reason,
            pnl=pnl,
        )

    def add_pyramid(
        self,
        base: Position,
        entry_price: float,
        new_sl: float,
        size: float,
        time: str,
        pyramid_level: int = 1,
    ) -> Position:
        """Create a pyramid add-on position anchored to the base trade's signal.

        Per spec §13.2:
          - Entry: price at the Impulse Leg LVN retest zone
          - SL: 2 ticks behind the LVN shelf (passed as new_sl)
          - TP: same as base trade's TP (structural target unchanged)
          - Size: 50% of base (P1) or 25% of base (P2)

        The base position's SL must be ratcheted to new_sl by the caller
        (runtime._check_pyramid) after this fills, so the combined bundle
        is guaranteed positive: SL is behind the new support level.
        """
        size = self._snap_to_lot(abs(size), self._lot_size)
        if size <= 0:
            raise ValueError(f"Pyramid size {size} is too small (< 1 lot)")

        base_signal = base.order.signal
        long = base.size > 0
        signed = size if long else -size

        # Build a synthetic signal for the pyramid position: inherit direction
        # and structural TP from the base trade, but update entry and SL.
        from quant.decision.signal_builder import Signal
        pyramid_signal = Signal(
            type=base_signal.type,
            reason=f"Pyramid-{pyramid_level} @ LVN {entry_price:.2f}",
            entry=entry_price,
            sl=new_sl,
            tp=base_signal.tp,    # same structural target
            rr=abs(base_signal.tp - entry_price) / max(abs(entry_price - new_sl), 0.01),
            model_label=getattr(base_signal, "model_label", "Triple-A"),
            symbol=base_signal.symbol,
            timestamp=time,
        )
        return Position(
            order=Order(signal=pyramid_signal, quantity=size),
            open_price=entry_price,
            open_time=time,
            size=signed,
            pyramid_level=pyramid_level,
            is_pyramid=True,
        )

    def close_partial(
        self,
        position: Position,
        fraction: float,
        price: float,
        time: str,
        reason: str,
    ) -> tuple["Fill", "Position"]:
        """Close a fraction of a position for multi-tier TP exits.

        Per spec §13.3:
          TP1 = 50% of position at +2R / first overhead LVN  (fraction=0.50)
          TP2 = 25% at macro VA extreme / CVD divergence       (fraction=0.25)
          Runner = remaining 25%, trailed                       (fraction=1.0)

        Returns:
          (Fill for the partial close, new Position with reduced size)
        """
        closed_size = position.size * fraction
        remaining_size = position.size * (1.0 - fraction)
        partial_pnl = (price - position.open_price) * closed_size

        fill_position = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=closed_size,
            realized_pnl=partial_pnl,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
        )
        fill = Fill(
            position=fill_position,
            close_price=price,
            close_time=time,
            reason=reason,
            pnl=partial_pnl,
        )
        # Remaining open position with reduced size — preserve _id so ExitEngine trail/breakeven persists
        remaining = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=remaining_size,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
            _id=position._id,
        )
        return fill, remaining
