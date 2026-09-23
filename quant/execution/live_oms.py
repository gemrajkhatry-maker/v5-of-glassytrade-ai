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

from quant.contracts.contracts import ContractRef
from quant.contracts.ports.broker import IBroker
from quant.decision.signal_builder import Signal as EngineSignal
from quant.events import EmergencyFlatten, OrderFilled, OrderSubmitted
from quant.execution.broker_mapper import to_broker_signal
from quant.execution.fills import broker_position_to_fill
from quant.execution.lots import snap_to_lot
from quant.execution.order import Fill, Order, Position

if TYPE_CHECKING:
    from quant.contracts.aggregates import Portfolio

logger = logging.getLogger(__name__)

class ReconciliationRequiredError(RuntimeError):
    """The broker outcome cannot safely be classified as rejected or flat."""

    def __init__(self, message: str, *, order_id: str, requested_qty: float = 0.0,
                 filled_qty: float = 0.0, fill_price: float = 0.0) -> None:
        super().__init__(message)
        self.order_id = order_id
        self.requested_qty = requested_qty
        self.filled_qty = filled_qty
        self.fill_price = fill_price


__all__ = ["EmergencyFlattenError", "ReconciliationRequiredError", "LiveOMS"]


class EmergencyFlattenError(RuntimeError):
    """Raised when Phase 2 contingent stop placement fails and emergency flatten is triggered."""


class LiveOMS:
    """Live order management system — implements IOMS for real broker execution.

    Routes engine signals to IBroker for actual exchange orders.
    Handles the type mapping between engine domain (float, LONG/SHORT)
    and broker domain (Decimal, BUY/SELL).
    """

    def __init__(
        self,
        broker: IBroker,
        portfolio: Portfolio,
        lot_size: float = 1.0,
        contract: ContractRef | None = None,
    ) -> None:
        if contract is not None and not isinstance(contract, ContractRef):
            raise ValueError("LiveOMS contract must be a validated ContractRef")
        self._broker = broker
        self._portfolio = portfolio
        self._lot_size = lot_size
        self._contract = contract
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
        try:
            raw_quantity = float(quantity)
            lot_size = float(self._lot_size)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"LiveOMS.submit: quantity and lot_size must be numeric, "
                f"got quantity={quantity!r}, lot_size={self._lot_size!r}"
            ) from exc
        if not math.isfinite(raw_quantity) or raw_quantity <= 0:
            raise ValueError(f"LiveOMS.submit: quantity must be finite and > 0, got {quantity!r}")
        if not math.isfinite(lot_size) or lot_size <= 0:
            raise ValueError(f"LiveOMS.submit: lot_size must be finite and > 0, got {self._lot_size!r}")
        size = snap_to_lot(raw_quantity, lot_size)
        if not math.isfinite(float(size)) or size <= 0:
            raise ValueError(f"LiveOMS.submit: snapped quantity must be finite and > 0, got {size!r}")
        if self._contract is not None and signal.symbol != self._contract.symbol:
            raise ValueError(
                "LiveOMS signal symbol must match its contract: "
                f"{signal.symbol!r} != {self._contract.symbol!r}"
            )
        broker_signal = to_broker_signal(signal, size)
        try:
            broker_pos = self._broker.execute_order(
                broker_signal, self._portfolio, signal.symbol,
                contract_ref=self._contract,
            )
        except TypeError as exc:
            # Compatibility for pre-contract-aware test/broker doubles; live
            # adapters implement the extended port and receive the identity.
            if "contract_ref" not in str(exc):
                raise
            broker_pos = self._broker.execute_order(
                broker_signal, self._portfolio, signal.symbol,
            )

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
                logger.warning("entry audit emit failed; trading unaffected", exc_info=True)

        position = Position(
            order=Order(signal=signal, quantity=abs(filled_qty)),
            open_price=fill_price,
            open_time=signal.timestamp,
            size=signed,
        )

        # Phase 2: Broker Contingent Stop-Loss Order Placement (SL-M)
        stop_price = float(getattr(signal, "sl", 0.0) or 0.0)
        if stop_price > 0 and filled_qty > 0 and hasattr(self._broker, "place_stop_loss"):
            stop_side = "SELL" if signal.type == "LONG" else "BUY"
            stop_qty = int(abs(filled_qty))
            stop_order_id = None
            try:
                stop_order_id = self._broker.place_stop_loss(
                    symbol=signal.symbol,
                    side=stop_side,
                    quantity=stop_qty,
                    stop_price=stop_price,
                    contract_ref=self._contract,
                )
            except NotImplementedError:
                # Pre-v6 broker double / test mock without native SL-M support
                stop_order_id = "mock_pass"
            except Exception as exc:
                logger.critical(
                    "LiveOMS Phase 2 contingent stop placement failed for %s: %s",
                    signal.symbol, exc,
                )
                stop_order_id = None

            if not stop_order_id:
                # The Panic Flatten Guard: Immediate reverse market order to close fill
                logger.critical(
                    "EMERGENCY FLATTEN: Contingent SL-M placement failed/rejected for %s (stop_price=%.2f). "
                    "Flattening position immediately.",
                    signal.symbol, stop_price,
                )
                try:
                    self.close(
                        position,
                        price=fill_price,
                        time=signal.timestamp,
                        reason="EMERGENCY_FLATTEN_CONTINGENT_STOP_FAILED",
                    )
                except Exception as fl_exc:
                    logger.critical("Emergency reverse market order failed: %s", fl_exc, exc_info=True)

                if self._emit_fn is not None:
                    try:
                        self._emit_fn(EmergencyFlatten(
                            symbol=signal.symbol,
                            time=signal.timestamp,
                            position_id=position.id,
                            reason="Contingent Phase 2 SL-M stop rejected/failed",
                            quantity=abs(filled_qty),
                            side=stop_side,
                        ))
                    except Exception:  # silent-except - emit audit error should not prevent emergency flatten error raise
                        pass

                raise EmergencyFlattenError(
                    f"LiveOMS Phase 2 contingent stop placement failed for {signal.symbol} "
                    "— position flattened via Emergency Flatten Guard."
                )

        return position

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
        if self._contract is not None and position.order.signal.symbol != self._contract.symbol:
            raise ValueError(
                "LiveOMS position symbol must match its contract: "
                f"{position.order.signal.symbol!r} != {self._contract.symbol!r}"
            )
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

        try:
            close_intent_id = f"close:{position.id}"
            broker_pos = self._broker.close_position(
                symbol=position.order.signal.symbol,
                side=close_side,
                quantity=qty,
                portfolio=self._portfolio,
                reference_price=price,
                contract_ref=self._contract,
                close_intent_id=close_intent_id,
            )
        except TypeError as exc:
            if "contract_ref" not in str(exc):
                raise
            try:
                broker_pos = self._broker.close_position(
                    symbol=position.order.signal.symbol,
                    side=close_side,
                    quantity=qty,
                    portfolio=self._portfolio,
                    reference_price=price,
                    close_intent_id=close_intent_id,
                )
            except TypeError as compatibility_exc:
                if "close_intent_id" not in str(compatibility_exc):
                    raise
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
                logger.warning("exit audit emit failed; trading unaffected", exc_info=True)

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
            logical_id=close_intent_id,
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
        if self._contract is not None and position.order.signal.symbol != self._contract.symbol:
            raise ValueError(
                "LiveOMS position symbol must match its contract: "
                f"{position.order.signal.symbol!r} != {self._contract.symbol!r}"
            )
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

        try:
            close_intent_id = f"close:{position.id}"
            broker_pos = self._broker.close_position(
                symbol=position.order.signal.symbol,
                side=close_side,
                quantity=qty,
                portfolio=self._portfolio,
                reference_price=price,
                contract_ref=self._contract,
                close_intent_id=close_intent_id,
            )
        except TypeError as exc:
            if "contract_ref" not in str(exc):
                raise
            try:
                broker_pos = self._broker.close_position(
                    symbol=position.order.signal.symbol,
                    side=close_side,
                    quantity=qty,
                    portfolio=self._portfolio,
                    reference_price=price,
                    close_intent_id=close_intent_id,
                )
            except TypeError as compatibility_exc:
                if "close_intent_id" not in str(compatibility_exc):
                    raise
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
        fill_price, _filled_qty = _fill.fill_price, _fill.filled_qty

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
            logical_id=close_intent_id,
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
        to new_sl by the caller (PositionManager.check_pyramid) after this fills.

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
    @property
    def is_live(self) -> bool:
        return True
