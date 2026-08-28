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

    def submit(self, signal: EngineSignal, quantity: float) -> Position:
        """Open a new position via the broker.

        Maps the engine signal to a broker signal, executes via IBroker,
        and maps the broker Position back to the engine domain Position.
        """
        size = self._snap_to_lot(quantity, self._lot_size)
        broker_signal = to_broker_signal(signal, size)
        broker_pos = self._broker.execute_order(broker_signal, self._portfolio, signal.symbol)

        if broker_pos is None:
            raise RuntimeError(
                f"LiveOMS.submit: broker rejected signal for {signal.symbol} "
                f"(side={signal.type}, entry={signal.entry}, qty={size})"
            )

        # Map broker Position → engine Position
        fill_price = float(getattr(broker_pos, "entry_price", 0))
        filled_qty = float(getattr(broker_pos, "size", 0))
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
        fill_price = float(getattr(broker_pos, "entry_price", price))
        filled_qty = float(getattr(broker_pos, "size", qty))

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

        fill_price = float(getattr(broker_pos, "entry_price", price))
        filled_qty = float(getattr(broker_pos, "size", qty))

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

        DISABLED UNDER LIVE OMS — E9 fix. Pyramids are additive and require an
        end-to-end broker submission path (propose → submit → fill → linked
        close) that does not yet exist for LiveOMS. Building in-memory positions
        here creates GHOST orders: PositionOpened fires but no broker order is
        ever placed, so the eventual full-close sends a broker.close_position()
        against an unopened position — a guaranteed live failure with wrong PnL.

        Until submit/linked-close is implemented for pyramids, this path refuses
        to build ghost positions and logs why. PaperOMS remains the only place
        pyramid add-ons are permitted (they are tracked in-memory there).
        """
        raise ValueError(
            "E9: pyramids disabled under LiveOMS until broker submission is "
            f"implemented end-to-end (propose→submit→fill→linked-close); requested "
            f"P{pyramid_level} @ {entry_price:.2f}"
        )

    @staticmethod
    def _snap_to_lot(quantity: float, lot_size: float) -> float:
        """Round a raw unit count to the nearest lot multiple (min 1 lot)."""
        if lot_size is None or lot_size <= 0 or quantity <= 0:
            return quantity
        num_lots = max(1.0, math.floor(quantity / lot_size + 0.5))
        return num_lots * lot_size
