"""LiveOMS — routes engine Signals to a real IBroker.

Implements the IOMS port for live trading. The coordinator injects this
when env=live; PaperOMS is used for paper/replay/backtest.

The engine never constructs its own OMS — the coordinator injects the
correct implementation at startup.

Signal flow:
  Engine Signal (LONG/SHORT, float entry/sl/tp)
    → broker_mapper.to_broker_signal()
    → IBroker.execute_order()  (for entries)
    → IBroker.close_position() (for exits)
    → mapping back to engine domain Position/Fill
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from quant.contracts.ports.broker import IBroker
from quant.decision.signal_builder import Signal as EngineSignal
from quant.events import OrderFilled, OrderSubmitted
from quant.execution.broker_mapper import to_broker_signal
from quant.execution.fills import broker_position_to_fill
from quant.execution.order import Fill, Order, Position

if TYPE_CHECKING:
    from quant.contracts.aggregates import Portfolio

logger = logging.getLogger(__name__)


class LiveOMS:
    """Live order management system — implements IOMS for real broker execution.

    Routes engine signals to IBroker for actual exchange orders.
    Handles the type mapping between engine domain (float, LONG/SHORT)
    and broker domain (Decimal, BUY/SELL).
    """

    def __init__(self, broker: IBroker, portfolio: Portfolio, lot_size: float = 1.0) -> None:
        self._broker = broker
        self._portfolio = portfolio
        self._lot_size = lot_size
        self._emit_fn = None  # set by coordinator after engine construction

    def set_emit_fn(self, emit_fn) -> None:
        """Wire the event emitter so audit events are published to the bus."""
        self._emit_fn = emit_fn

    @property
    def lot_size(self) -> float:
        return self._lot_size

    def submit(self, signal: EngineSignal, quantity: float) -> Position | None:
        """Open a new position via the broker.

        Maps the engine signal to a broker signal, executes via IBroker,
        and maps the broker Position back to the engine domain Position.
        Returns None if the broker rejected the signal (normal, not an error).
        """
        size = self._snap_to_lot(quantity, self._lot_size)
        broker_signal = to_broker_signal(signal, size)
        broker_pos = self._broker.execute_order(broker_signal, self._portfolio, signal.symbol)

        if broker_pos is None:
            # Broker rejection: raise so the engine's submit-error path unwinds
            # the portfolio-risk reservation and journals the failure. A silent
            # None return previously let a phantom zero-size position through
            # to PositionOpened. The engine catches this and stays alive.
            raise RuntimeError(
                f"LiveOMS.submit: broker rejected signal for {signal.symbol} "
                f"(side={signal.type}, entry={signal.entry}, qty={size}) "
                f"— broker rejected the order"
            )

        # Map broker Position → engine Position
        _fill = broker_position_to_fill(broker_pos, fallback_price=0.0, fallback_qty=0.0)
        fill_price, filled_qty = _fill.fill_price, _fill.filled_qty
        signed = filled_qty if signal.type == "LONG" else -filled_qty

        # Audit trail: order was filled
        if self._emit_fn is not None:
            try:
                self._emit_fn(OrderSubmitted(
                    symbol=signal.symbol, time=signal.timestamp,
                    side="BUY" if signal.type == "LONG" else "SELL",
                    quantity=filled_qty, price=fill_price, reason="ENTRY",
                ))
                self._emit_fn(OrderFilled(
                    symbol=signal.symbol, time=signal.timestamp,
                    fill_price=fill_price, filled_qty=filled_qty, reason="ENTRY",
                ))
            except Exception:
                pass  # audit must never break trading

        return Position(
            order=Order(signal=signal, quantity=abs(filled_qty)),
            open_price=fill_price,
            open_time=signal.timestamp,
            size=signed,
        )

    def close(
        self,
        position: Position,
        price: float,
        time: str,
        reason: str,
    ) -> Fill:
        """Close an entire position via the broker.

        Places an opposing market order (SELL to close LONG, BUY to close SHORT)
        and returns a Fill with the actual broker fill price.
        """
        long = position.size > 0
        close_side = "SELL" if long else "BUY"
        qty = abs(int(position.size))

        if qty <= 0:
            logger.warning("LiveOMS.close: position size is 0 for %s", position._id)
            # Return a zero-pnl fill — position was already closed
            return Fill(
                position=position,
                close_price=price,
                close_time=time,
                reason=reason,
                pnl=0.0,
            )

        broker_pos = self._broker.close_position(
            symbol=position.order.signal.symbol,
            side=close_side,
            quantity=qty,
            portfolio=self._portfolio,
            reference_price=price,
        )

        if broker_pos is None:
            raise RuntimeError(
                f"LiveOMS.close: broker failed to close position {position._id} "
                f"(symbol={position.order.signal.symbol}, side={close_side}, qty={qty})"
            )

        # The broker returns entry_price = actual fill price for close orders
        _fill = broker_position_to_fill(broker_pos, fallback_price=price, fallback_qty=qty)
        fill_price, filled_qty = _fill.fill_price, _fill.filled_qty

        # Audit trail: close order was filled
        if self._emit_fn is not None:
            try:
                self._emit_fn(OrderSubmitted(
                    symbol=position.order.signal.symbol, time=time,
                    side=close_side, quantity=float(filled_qty),
                    price=fill_price, reason=reason,
                ))
                self._emit_fn(OrderFilled(
                    symbol=position.order.signal.symbol, time=time,
                    fill_price=fill_price, filled_qty=filled_qty, reason=reason,
                ))
            except Exception:
                pass

        # PnL = (close_price - entry_price) * signed_size
        pnl = (fill_price - position.open_price) * position.size

        closed_position = Position(
            order=position.order,
            open_price=position.open_price,
            open_time=position.open_time,
            size=position.size,
            realized_pnl=pnl,
            pyramid_level=position.pyramid_level,
            is_pyramid=position.is_pyramid,
        )

        return Fill(
            position=closed_position,
            close_price=fill_price,
            close_time=time,
            reason=reason,
            pnl=pnl,
        )

    def close_partial(
        self,
        position: Position,
        fraction: float,
        price: float,
        time: str,
        reason: str,
    ) -> tuple[Fill, Position]:
        """Close a fraction of a position (spec §13.3 tiered TP).

        Places an opposing market order for the partial quantity.
        """
        closed_size = position.size * fraction
        remaining_size = position.size * (1.0 - fraction)

        long = position.size > 0
        close_side = "SELL" if long else "BUY"
        qty = abs(int(closed_size))

        if qty <= 0:
            logger.warning("LiveOMS.close_partial: computed qty=0 for fraction=%.2f", fraction)
            return (
                Fill(
                    position=Position(
                        order=position.order,
                        open_price=position.open_price,
                        open_time=position.open_time,
                        size=0.0,
                        realized_pnl=0.0,
                        pyramid_level=position.pyramid_level,
                        is_pyramid=position.is_pyramid,
                    ),
                    close_price=price,
                    close_time=time,
                    reason=reason,
                    pnl=0.0,
                ),
                position,
            )

        broker_pos = self._broker.close_position(
            symbol=position.order.signal.symbol,
            side=close_side,
            quantity=qty,
            portfolio=self._portfolio,
            reference_price=price,
        )

        if broker_pos is None:
            raise RuntimeError(
                f"LiveOMS.close_partial: broker failed for {position._id} "
                f"(fraction={fraction}, qty={qty})"
            )

        _fill = broker_position_to_fill(broker_pos, fallback_price=price, fallback_qty=qty)
        fill_price, filled_qty = _fill.fill_price, _fill.filled_qty

        partial_pnl = (fill_price - position.open_price) * closed_size

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
            close_price=fill_price,
            close_time=time,
            reason=reason,
            pnl=partial_pnl,
        )

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

    def add_pyramid(
        self,
        base: Position,
        entry_price: float,
        new_sl: float,
        size: float,
        time: str,
        pyramid_level: int = 1,
    ) -> Position:
        """Create a pyramid add-on position anchored to the base trade (spec §13.2).

        Per spec §13.2:
          - Entry: price at the Impulse Leg LVN retest zone
          - SL: 2 ticks behind the LVN shelf (passed as new_sl)
          - TP: same as base trade's TP (structural target unchanged)
          - Size: 50% of base (P1) or 25% of base (P2)

        Routes through IBroker.execute_order() so the pyramid is a real broker
        order, not a ghost position. The base position's SL must be ratcheted
        to new_sl by the caller (runtime._check_pyramid) after this fills.

        E9: pyramids are DISABLED under LiveOMS until end-to-end
        submit→fill→linked-close is implemented. Creating an in-memory
        pyramid Position here would be a ghost — it exists in the engine but
        the broker has no matching order, so the close path would fail on a
        position the broker never opened. Callers (PositionManager.
        check_pyramid) catch this ValueError and skip the add-on.
        """
        raise ValueError(
            "E9: pyramids disabled under LiveOMS — submit→fill→linked-close "
            "not implemented end-to-end; refusing to create a ghost pyramid "
            "position"
        )
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

        # Submit to broker (same path as submit())
        broker_signal = to_broker_signal(pyramid_signal, size)
        broker_pos = self._broker.execute_order(broker_signal, self._portfolio, pyramid_signal.symbol)

        if broker_pos is None:
            logger.warning(
                "LiveOMS.add_pyramid: broker rejected pyramid for %s "
                "(side=%s, entry=%s, qty=%s) — skipping pyramid",
                pyramid_signal.symbol, pyramid_signal.type, entry_price, size,
            )
            return None

        _fill = broker_position_to_fill(broker_pos, fallback_price=entry_price, fallback_qty=size)
        fill_price, filled_qty = _fill.fill_price, _fill.filled_qty
        signed = filled_qty if long else -filled_qty

        # Audit trail
        if self._emit_fn is not None:
            try:
                self._emit_fn(OrderSubmitted(
                    symbol=pyramid_signal.symbol, time=time,
                    side="BUY" if long else "SELL",
                    quantity=filled_qty, price=fill_price, reason=f"PYRAMID_{pyramid_level}",
                ))
                self._emit_fn(OrderFilled(
                    symbol=pyramid_signal.symbol, time=time,
                    fill_price=fill_price, filled_qty=filled_qty, reason=f"PYRAMID_{pyramid_level}",
                ))
            except Exception:
                pass  # audit must never break trading

        return Position(
            order=Order(signal=pyramid_signal, quantity=abs(filled_qty)),
            open_price=fill_price,
            open_time=time,
            size=signed,
            pyramid_level=pyramid_level,
            is_pyramid=True,
        )

    @staticmethod
    def _snap_to_lot(quantity: float, lot_size: float) -> float:
        """Round a raw unit count to the nearest lot multiple (min 1 lot)."""
        if lot_size is None or lot_size <= 0 or quantity <= 0:
            return quantity
        num_lots = max(1.0, math.floor(quantity / lot_size + 0.5))
        return num_lots * lot_size
