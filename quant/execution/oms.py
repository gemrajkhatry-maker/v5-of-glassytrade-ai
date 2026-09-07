from quant.decision.signal_builder import Signal
from quant.execution.lots import snap_to_lot
from quant.execution.order import Fill, Order, Position
from quant.execution.ports import IOMS
from quant.execution.paper_contracts import PaperContract
from quant.execution.paper_simulator import PaperExecutionSimulator, PaperFill
from quant.contracts.contracts import ContractRef


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

    def __init__(
        self,
        lot_size: float = 1.0,
        *,
        simulator: PaperExecutionSimulator | None = None,
        contract: ContractRef | None = None,
        quote_provider=None,
    ) -> None:
        self._lot_size = lot_size
        self._simulator = simulator
        self._contract = contract
        self._quote_provider = quote_provider
        self.last_fill: PaperFill | None = None

    def _quote(self) -> tuple[float, float]:
        """Return the current executable bid/ask, or an invalid quote.

        The production factory configures ``bid_ask`` mode.  Returning zeros
        here deliberately causes the simulator to reject an order when market
        depth is absent; it must never silently downgrade to a reference-price
        fill.
        """
        if self._quote_provider is None:
            return 0.0, 0.0
        try:
            quote = self._quote_provider()
            if quote is None:
                return 0.0, 0.0
            bid, ask = quote
            return float(bid), float(ask)
        except Exception:
            return 0.0, 0.0

    @property
    def lot_size(self) -> float:
        return self._lot_size

    def set_quote_provider(self, quote_provider) -> None:
        """Attach the current executable quote source after construction."""
        self._quote_provider = quote_provider

    def submit(self, signal: Signal, quantity: float) -> Position:
        if self._simulator is not None:
            if self._contract is None:
                raise ValueError("PaperOMS simulator mode requires a ContractRef")
            order_id = f"entry:{signal.signal_id}"
            paper_fill = self._simulator.submit(
                order_id=order_id,
                contract=self._contract,
                side="BUY" if signal.type == "LONG" else "SELL",
                quantity=int(snap_to_lot(quantity, self._lot_size)),
                reference_price=signal.entry,
                bid=self._quote()[0],
                ask=self._quote()[1],
            )
            self.last_fill = paper_fill
            size = float(paper_fill.filled_quantity)
            signed = size if signal.type == "LONG" else -size
            return Position(
                order=Order(signal=signal, quantity=size),
                open_price=paper_fill.fill_price,
                open_time=signal.timestamp,
                size=signed,
                entry_costs=paper_fill.costs,
            )
        size = snap_to_lot(quantity, self._lot_size)
        signed = size if signal.type == "LONG" else -size
        return Position(
            order=Order(signal=signal, quantity=size),
            open_price=signal.entry,
            open_time=signal.timestamp,
            size=signed,
        )

    def close(self, position: Position, price: float, time: str, reason: str) -> Fill:
        if self._simulator is not None:
            if self._contract is None:
                raise ValueError("PaperOMS simulator mode requires a ContractRef")
            paper_fill = self._simulator.submit(
                order_id=f"close:{position.id}:{time}:{reason}",
                contract=self._contract,
                side="SELL" if position.size > 0 else "BUY",
                quantity=int(abs(position.size)),
                reference_price=price,
                bid=self._quote()[0],
                ask=self._quote()[1],
            )
            self.last_fill = paper_fill
            gross = (paper_fill.fill_price - position.open_price) * position.size
            entry_costs = position.entry_costs.total if position.entry_costs is not None else 0.0
            pnl = gross - entry_costs - paper_fill.costs.total
            closed = Position(
                order=position.order,
                open_price=position.open_price,
                open_time=position.open_time,
                size=position.size,
                realized_pnl=pnl,
                entry_costs=position.entry_costs,
                pyramid_level=position.pyramid_level,
                is_pyramid=position.is_pyramid,
                _id=position.id,
            )
            return Fill(
                position=closed,
                close_price=paper_fill.fill_price,
                close_time=time,
                reason=reason,
                pnl=pnl,
                costs=paper_fill.costs,
                logical_id=f"close:{position.id}:{time}:{reason}",
            )
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
        size = snap_to_lot(abs(size), self._lot_size)
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
        if self._simulator is not None:
            lots = int(abs(position.size) / self._lot_size)
            close_lots = max(1, round(lots * fraction))
            close_lots = min(lots, close_lots)
            closed_size = (1 if position.size > 0 else -1) * close_lots * self._lot_size
        remaining_size = position.size * (1.0 - fraction)
        if self._simulator is not None:
            remaining_size = position.size - closed_size
        close_price = price
        if self._simulator is not None:
            if self._contract is None:
                raise ValueError("PaperOMS simulator mode requires a ContractRef")
            paper_fill = self._simulator.submit(
                order_id=f"partial:{position.id}:{time}:{reason}",
                contract=self._contract,
                side="SELL" if position.size > 0 else "BUY",
                quantity=int(abs(closed_size)),
                reference_price=price,
                bid=self._quote()[0],
                ask=self._quote()[1],
            )
            self.last_fill = paper_fill
            close_price = paper_fill.fill_price
            fraction = abs(closed_size) / max(abs(position.size), 1.0)
            entry_costs = position.entry_costs.prorated(fraction) if position.entry_costs else None
            partial_pnl = (
                (close_price - position.open_price) * closed_size
                - (entry_costs.total if entry_costs else 0.0)
                - paper_fill.costs.total
            )
        else:
            partial_pnl = (price - position.open_price) * closed_size

        fill_position = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=closed_size,
            realized_pnl=partial_pnl,
            entry_costs=entry_costs if self._simulator is not None else None,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
        )
        fill = Fill(
            position=fill_position,
            close_price=close_price,
            close_time=time,
            reason=reason,
            pnl=partial_pnl,
            costs=paper_fill.costs if self._simulator is not None else None,
            logical_id=(
                f"partial:{position.id}:{time}:{reason}"
                if self._simulator is not None else ""
            ),
        )
        # Remaining open position with reduced size — preserve _id so ExitEngine trail/breakeven persists
        remaining = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=remaining_size,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
            entry_costs=(
                position.entry_costs.prorated(max(0.0, abs(remaining_size) / max(abs(position.size), 1.0)))
                if self._simulator is not None and position.entry_costs is not None else position.entry_costs
            ),
            _id=position._id,
        )
        return fill, remaining
